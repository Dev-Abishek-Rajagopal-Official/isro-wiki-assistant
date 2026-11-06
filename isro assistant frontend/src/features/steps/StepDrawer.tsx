/**
 * Details drawer: opened from any step. Shows the router decision and its structured block, a sub-agent's
 * rewritten query, every tool call with what it returned, the generated content, LLM call stats, what the
 * step changed in the AgentState, and the run summary.
 */
import { AlertTriangle, CheckCircle2, Wrench } from "lucide-react";
import { useState } from "react";
import { useAppDispatch, useAppSelector } from "../../app/hooks";
import { Drawer } from "../../components/Drawer";
import { JsonView } from "../../components/JsonView";
import { Markdown } from "../../components/Markdown";
import { Tabs } from "../../components/Tabs";
import { Badge, Card, EmptyState, fmt } from "../../components/ui";
import { SUB_AGENTS, type Source, type Usage } from "../../lib/types";
import type { LiveRun } from "../runs/runsSlice";
import { uiActions } from "../ui/uiSlice";
import { AGENT_SOURCES, buildSteps, duration, label, summarizeResult, type Step } from "./buildSteps";
import { ToolResultView } from "./ToolResultView";

/* eslint-disable @typescript-eslint/no-explicit-any */
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</h3>
      {children}
    </section>
  );
}

function LlmCalls({ calls }: { calls: Record<string, any>[] }) {
  if (!calls.length) return <p className="text-sm text-slate-500">No LLM calls recorded for this step.</p>;
  return (
    <div className="space-y-2">
      {calls.map((c, i) => (
        <Card key={i} className="p-3 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="violet">{c.role}</Badge>
            <span className="text-slate-600">{c.model}</span>
            <span className="ml-auto text-xs text-slate-500">{fmt.secs(c.seconds)}</span>
          </div>
          <div className="mt-2 grid grid-cols-4 gap-2 text-xs">
            {[["input", c.input_tokens], ["output", c.output_tokens], ["reasoning", c.reasoning_tokens], ["cached", c.cached_tokens]].map(([k, v]) => (
              <div key={k as string} className="rounded bg-slate-50 px-2 py-1"><div className="text-slate-400">{k}</div><div className="font-medium text-slate-800">{fmt.int(v as number)}</div></div>
            ))}
          </div>
          {c.ratelimit_remaining_tokens != null && (
            <div className="mt-1 text-[11px] text-slate-400">Azure rate limit remaining: {fmt.int(c.ratelimit_remaining_tokens)} tokens{c.ratelimit_remaining_requests != null && ` · ${fmt.int(c.ratelimit_remaining_requests)} requests`}</div>
          )}
        </Card>
      ))}
    </div>
  );
}

function Changes({ changes }: { changes: Record<string, unknown>[] }) {
  if (!changes.length) return <p className="text-sm text-slate-500">No state changes recorded.</p>;
  return <div className="space-y-2">{changes.map((c, i) => <JsonView key={i} value={c} />)}</div>;
}

function Sources({ sources }: { sources?: Source[] }) {
  if (!sources?.length) return null;
  return (
    <ul className="space-y-1 text-sm">
      {sources.map((s, i) => (
        <li key={i} className="flex items-start gap-2">
          <span className="mt-0.5 text-xs text-slate-400">{s.n ?? i + 1}.</span>
          {s.url ? <a href={s.url} target="_blank" rel="noopener noreferrer" className="text-brand-600 hover:underline">{s.title}</a> : <span>{s.title}</span>}
        </li>
      ))}
    </ul>
  );
}

function RouterPanel({ step }: { step: Step }) {
  const [tab, setTab] = useState<"decision" | "block" | "llm" | "changes">("decision");
  const d = step.decision ?? {};
  return (
    <>
      <Tabs className="px-5" value={tab} onChange={setTab} tabs={[
        { id: "decision", label: "Decision" }, { id: "block", label: "Structured block" },
        { id: "llm", label: "LLM call", count: step.llm.length }, { id: "changes", label: "State changes" }]} />
      <div className="space-y-5 p-5">
        {tab === "decision" && (
          <>
            <Section title="Next">
              <div className="flex items-center gap-2 text-sm">
                <Badge tone="blue">{label(d.next_agent)}</Badge>
                {d.overridden && <Badge tone="amber">guardrail changed the model's choice ({label(d.model_choice)})</Badge>}
              </div>
            </Section>
            {d.task && <Section title="Task for the agent"><p className="text-sm text-slate-700">{d.task}</p></Section>}
            {d.reason && <Section title="Why"><p className="text-sm text-slate-700">{d.reason}</p></Section>}
          </>
        )}
        {tab === "block" && (
          <Section title="Router's structured state at this decision">
            <JsonView value={{ next_agent: d.next_agent, task: d.task, reason: d.reason,
              ...Object.fromEntries([...SUB_AGENTS, "final_agent"].map((a) => [a, d[a] ?? ""])) }} />
          </Section>
        )}
        {tab === "llm" && <LlmCalls calls={step.llm} />}
        {tab === "changes" && <Changes changes={step.changes} />}
      </div>
    </>
  );
}

function AgentPanel({ step }: { step: Step }) {
  const [tab, setTab] = useState<"overview" | "tools" | "content" | "llm" | "changes">("tools");
  return (
    <>
      <Tabs className="px-5" value={tab} onChange={setTab} tabs={[
        { id: "overview", label: "Overview" }, { id: "tools", label: "Tool calls", count: step.tools.length },
        { id: "content", label: "Findings" }, { id: "llm", label: "LLM calls", count: step.llm.length },
        { id: "changes", label: "State changes" }]} />
      <div className="space-y-5 p-5">
        {tab === "overview" && (
          <>
            <Section title="Data source"><p className="text-sm text-slate-700">{AGENT_SOURCES[step.node] ?? step.node}</p></Section>
            {step.task && <Section title="Task from the router"><p className="text-sm text-slate-700">{step.task}</p></Section>}
            {step.rewrites.map((r, i) => (
              <Section key={i} title={r.retry ? "Retry: rewritten request" : "Rewritten request (intermediate LLM)"}>
                <p className="text-sm text-slate-700">{r.rewritten_query}</p>
                <div className="flex flex-wrap gap-1">{r.tool_calls.map((c, j) => <Badge key={j} tone="blue">{c.tool}({c.arguments_json})</Badge>)}</div>
              </Section>
            ))}
          </>
        )}
        {tab === "tools" && (step.tools.length ? step.tools.map((t) => (
          <Card key={t.id} className="space-y-3 p-4">
            <div className="flex flex-wrap items-center gap-2">
              {t.status === "ok" ? <CheckCircle2 className="h-4 w-4 text-emerald-500" /> : t.status === "running" ? <Wrench className="h-4 w-4 animate-pulse text-brand-600" /> : <AlertTriangle className="h-4 w-4 text-amber-500" />}
              <span className="font-mono text-sm font-medium text-slate-800">{t.tool}</span>
              <Badge tone={t.status === "ok" ? "green" : t.status === "running" ? "blue" : "amber"}>
                {t.status === "ok" ? summarizeResult(t.tool, t.result) : t.status}
              </Badge>
              {t.durationMs != null && <span className="ml-auto text-xs text-slate-500">{fmt.secs(t.durationMs / 1000)}</span>}
            </div>
            <div>
              <div className="mb-1 text-xs font-medium text-slate-500">Arguments</div>
              <JsonView value={t.args} />
            </div>
            {t.error && <p className="text-sm text-amber-700">{t.error}</p>}
            {t.status !== "running" && (
              <div>
                <div className="mb-1 text-xs font-medium text-slate-500">Returned</div>
                <ToolResultView result={t.result} />
              </div>
            )}
          </Card>
        )) : <p className="text-sm text-slate-500">No tool calls yet.</p>)}
        {tab === "content" && (step.content
          ? <><Markdown text={step.content} sources={step.sources} /><Section title="Sources"><Sources sources={step.sources} /></Section></>
          : <p className="text-sm text-slate-500">Still working…</p>)}
        {tab === "llm" && <LlmCalls calls={step.llm} />}
        {tab === "changes" && <Changes changes={step.changes} />}
      </div>
    </>
  );
}

function FinalPanel({ step, run }: { step: Step; run: LiveRun }) {
  const [tab, setTab] = useState<"answer" | "llm">("answer");
  return (
    <>
      <Tabs className="px-5" value={tab} onChange={setTab} tabs={[{ id: "answer", label: "Answer" }, { id: "llm", label: "LLM call", count: step.llm.length }]} />
      <div className="space-y-5 p-5">
        {tab === "answer" && (
          <>
            <Markdown text={run.answer || "…"} sources={run.sources} />
            <Section title="Numbered sources"><Sources sources={run.sources} /></Section>
          </>
        )}
        {tab === "llm" && <LlmCalls calls={step.llm} />}
      </div>
    </>
  );
}

function UsageTable({ usage }: { usage: Usage | null }) {
  if (!usage?.by_role) return <p className="text-sm text-slate-500">Usage appears when the run finishes.</p>;
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200">
      <table className="min-w-full text-xs">
        <thead className="bg-slate-50 text-left text-slate-500">
          <tr><th className="px-2 py-1.5">LLM role</th><th className="px-2 py-1.5">calls</th><th className="px-2 py-1.5">input</th><th className="px-2 py-1.5">output</th><th className="px-2 py-1.5">reasoning</th></tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {Object.entries(usage.by_role).map(([role, u]) => (
            <tr key={role}><td className="px-2 py-1.5 font-medium">{role}</td><td className="px-2 py-1.5">{u.llm_calls}</td><td className="px-2 py-1.5">{fmt.int(u.input_tokens)}</td><td className="px-2 py-1.5">{fmt.int(u.output_tokens)}</td><td className="px-2 py-1.5">{fmt.int(u.reasoning_tokens)}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SummaryPanel({ run }: { run: LiveRun }) {
  const [tab, setTab] = useState<"summary" | "state">("summary");
  const prev = run.prevAgentState ?? {};
  const changed = new Set(Object.keys(run.agentState ?? {}).filter((k) =>
    JSON.stringify((run.agentState as any)?.[k]) !== JSON.stringify((prev as any)[k])));
  return (
    <>
      <Tabs className="px-5" value={tab} onChange={setTab} tabs={[{ id: "summary", label: "Summary" }, { id: "state", label: "AgentState" }]} />
      <div className="space-y-5 p-5">
        {tab === "summary" && (
          <>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Card className="p-3"><div className="text-xs text-slate-500">Time</div><div className="font-semibold">{fmt.secs(run.seconds)}</div></Card>
              <Card className="p-3"><div className="text-xs text-slate-500">LLM calls</div><div className="font-semibold">{fmt.int(run.runUsage?.llm_calls)}</div></Card>
              <Card className="p-3"><div className="text-xs text-slate-500">Input tokens</div><div className="font-semibold">{fmt.int(run.runUsage?.input_tokens)}</div></Card>
              <Card className="p-3"><div className="text-xs text-slate-500">Output tokens</div><div className="font-semibold">{fmt.int(run.runUsage?.output_tokens)}</div></Card>
            </div>
            <Section title="Agents used">
              <div className="flex flex-wrap gap-1">{run.agentsUsed.length ? run.agentsUsed.map((a) => <Badge key={a} tone="blue">{label(a)}</Badge>) : <span className="text-sm text-slate-500">none (answered without data sources)</span>}</div>
            </Section>
            <Section title="Tokens by LLM role"><UsageTable usage={run.runUsage} /></Section>
            {run.threadUsage && <Section title="Thread total"><p className="text-sm text-slate-700">{fmt.int(run.threadUsage.llm_calls)} LLM calls · {fmt.int(run.threadUsage.input_tokens)} input · {fmt.int(run.threadUsage.output_tokens)} output tokens</p></Section>}
          </>
        )}
        {tab === "state" && (run.agentState
          ? <><p className="text-xs text-slate-500">Highlighted keys changed in the latest update.</p><JsonView value={run.agentState} highlight={changed} /></>
          : <p className="text-sm text-slate-500">No state yet.</p>)}
      </div>
    </>
  );
}

export function StepDrawerHost() {
  const dispatch = useAppDispatch();
  const target = useAppSelector((s) => s.ui.drawer);
  const run = useAppSelector((s) => (target ? s.runs.byThread[target.threadId] : undefined));
  const close = () => dispatch(uiActions.closeDrawer());
  if (!target) return null;
  if (!run) {
    return <Drawer open title="Details" onClose={close}><EmptyState title="This run is no longer loaded" /></Drawer>;
  }
  if (target.stepId === "summary") {
    return <Drawer open wide title="Run details" subtitle={run.question} onClose={close}><SummaryPanel run={run} /></Drawer>;
  }
  const step = buildSteps(run).find((s) => s.id === target.stepId);
  if (!step) return <Drawer open title="Details" onClose={close}><EmptyState title="Step not found" /></Drawer>;
  const secs = duration(step.startedAt, step.endedAt);
  return (
    <Drawer open wide onClose={close}
      title={<span className="flex items-center gap-2">{step.title}{step.status === "running" && <Badge tone="blue">running</Badge>}{step.status === "failed" && <Badge tone="amber">failed</Badge>}</span>}
      subtitle={<span className="flex items-center gap-2">{step.detail}{secs != null && <span className="text-slate-400">· {fmt.secs(secs)}</span>}</span>}>
      {step.kind === "router" && <RouterPanel step={step} />}
      {step.kind === "agent" && <AgentPanel step={step} />}
      {step.kind === "final" && <FinalPanel step={step} run={run} />}
    </Drawer>
  );
}
