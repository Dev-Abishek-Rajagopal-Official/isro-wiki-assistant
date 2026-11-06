/**
 * Live stepper under each question: one row per agent step with loading / done / failed state, nested tool
 * calls, and durations. Every row opens the details drawer. Collapses to a one-line summary when finished.
 */
import { AlertTriangle, BookOpen, CheckCircle2, ChevronDown, ChevronRight, Database, Loader2, Mic, Orbit, PenLine, Rocket, Route, Wrench } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useAppDispatch } from "../../app/hooks";
import { cx, fmt } from "../../components/ui";
import type { LiveRun } from "../runs/runsSlice";
import { uiActions } from "../ui/uiSlice";
import { buildSteps, duration, type Step } from "./buildSteps";

const ICONS: Record<string, ReactNode> = {
  speech: <Mic className="h-4 w-4" />,
  router: <Route className="h-4 w-4" />,
  rag_agent: <BookOpen className="h-4 w-4" />,
  launch_agent: <Rocket className="h-4 w-4" />,
  wikidata_agent: <Database className="h-4 w-4" />,
  celestrak_agent: <Orbit className="h-4 w-4" />,
  final_agent: <PenLine className="h-4 w-4" />,
};

function StatusIcon({ status }: { status: Step["status"] }) {
  if (status === "running") return <Loader2 className="h-4 w-4 animate-spin text-brand-600" aria-label="in progress" />;
  if (status === "failed") return <AlertTriangle className="h-4 w-4 text-amber-500" aria-label="failed" />;
  if (status === "done") return <CheckCircle2 className="h-4 w-4 text-emerald-500" aria-label="done" />;
  return <span className="h-4 w-4 rounded-full border-2 border-slate-300" />;
}

function StepRow({ step, onOpen }: { step: Step; onOpen?: () => void }) {
  const secs = duration(step.startedAt, step.endedAt);
  const clickable = !!onOpen && step.kind !== "waiting" && step.kind !== "transcribe";
  return (
    <li>
      <button type="button" disabled={!clickable} onClick={onOpen}
        className={cx("group flex w-full items-start gap-3 rounded-lg px-2 py-1.5 text-left transition",
          clickable && "hover:bg-white hover:shadow-sm")}>
        <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-white text-slate-500 ring-1 ring-slate-200">
          {ICONS[step.node] ?? <Wrench className="h-4 w-4" />}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2">
            <span className={cx("text-sm font-medium", step.status === "waiting" ? "text-slate-400" : "text-slate-800")}>{step.title}</span>
            <StatusIcon status={step.status} />
            {secs != null && step.kind !== "router" && <span className="text-xs text-slate-400">{fmt.secs(secs)}</span>}
          </span>
          {step.detail && <span className="mt-0.5 block truncate text-xs text-slate-500">{step.detail}</span>}
          {step.tools.length > 0 && (
            <span className="mt-1 flex flex-wrap gap-1">
              {step.tools.map((t) => (
                <span key={t.id} className={cx("inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] ring-1",
                  t.status === "running" ? "bg-brand-50 text-brand-700 ring-brand-100" :
                  t.status === "ok" ? "bg-emerald-50 text-emerald-700 ring-emerald-100" :
                  t.status === "empty" ? "bg-slate-50 text-slate-500 ring-slate-200" : "bg-amber-50 text-amber-700 ring-amber-100")}>
                  {t.status === "running" ? <Loader2 className="h-3 w-3 animate-spin" /> : <Wrench className="h-3 w-3" />}
                  {t.tool}{t.durationMs != null && ` · ${fmt.secs(t.durationMs / 1000)}`}
                </span>
              ))}
            </span>
          )}
        </span>
        {clickable && <ChevronRight className="mt-1 h-4 w-4 shrink-0 text-slate-300 group-hover:text-slate-500" />}
      </button>
    </li>
  );
}

export function StepList({ run, threadKey, defaultOpen }: { run: LiveRun; threadKey: string; defaultOpen?: boolean }) {
  const dispatch = useAppDispatch();
  const steps = buildSteps(run);
  const finished = run.status === "succeeded" || run.status === "failed" || run.status === "cancelled";
  const [expanded, setExpanded] = useState<boolean | null>(defaultOpen ?? null);
  const open = expanded ?? !finished;
  if (!steps.length) return null;

  const agents = steps.filter((s) => s.kind === "agent").length;
  const tokens = (run.runUsage?.input_tokens ?? 0) + (run.runUsage?.output_tokens ?? 0);
  const openStep = (s: Step) => dispatch(uiActions.openDrawer({
    source: threadKey.startsWith("history:") ? "history" : "live", threadId: threadKey, runId: run.runId, stepId: s.id,
  }));

  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50/70">
      <button type="button" onClick={() => setExpanded(!open)} aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-slate-500 hover:text-slate-700">
        {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        {finished ? (
          <span>
            {steps.filter((s) => s.kind !== "waiting").length} steps · {agents} {agents === 1 ? "agent" : "agents"}
            {run.seconds != null && ` · ${fmt.secs(run.seconds)}`}{tokens > 0 && ` · ${fmt.compact(tokens)} tokens`}
          </span>
        ) : (
          <span className="flex items-center gap-1.5 font-medium text-brand-700"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Working on it…</span>
        )}
        {finished && (
          <span role="button" tabIndex={0} onClick={(e) => { e.stopPropagation(); dispatch(uiActions.openDrawer({ source: threadKey.startsWith("history:") ? "history" : "live", threadId: threadKey, runId: run.runId, stepId: "summary" })); }}
            className="ml-auto rounded px-1.5 py-0.5 text-brand-600 hover:bg-brand-50">Run details</span>
        )}
      </button>
      {open && (
        <ol className="space-y-0.5 px-1.5 pb-2" aria-live="polite">
          {steps.map((s) => <StepRow key={s.id} step={s} onOpen={() => openStep(s)} />)}
        </ol>
      )}
    </div>
  );
}
