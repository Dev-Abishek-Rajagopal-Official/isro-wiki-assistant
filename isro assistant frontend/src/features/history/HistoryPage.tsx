/**
 * Thread history: pick any past run -> its steps are rebuilt from the stored events (same stepper and
 * drawer as live), plus an AgentState timeline (LangGraph checkpoints) you can step through.
 */
import { ArrowLeft, ChevronLeft, ChevronRight, Mic } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useAppDispatch, useAppSelector } from "../../app/hooks";
import { JsonView } from "../../components/JsonView";
import { Markdown } from "../../components/Markdown";
import { Badge, Card, cx, EmptyState, fmt, Skeleton } from "../../components/ui";
import { storedToMessage } from "../../lib/events";
import { useThreadEventsQuery, useThreadQuery, useThreadStatesQuery } from "../../services/api";
import { runsActions } from "../runs/runsSlice";
import { label } from "../steps/buildSteps";
import { StepList } from "../steps/StepList";

function RunReplay({ threadId, runId }: { threadId: string; runId: string }) {
  const dispatch = useAppDispatch();
  const key = `history:${runId}`;
  const { data: events, isLoading } = useThreadEventsQuery({ threadId, runId });
  const run = useAppSelector((s) => s.runs.byThread[key]);

  useEffect(() => {
    if (!events) return;
    dispatch(runsActions.cleared(key));
    events.forEach((e) => dispatch(runsActions.messageReceived(storedToMessage({ ...e, run_id: runId }, key))));
  }, [events, key, runId, dispatch]);

  if (isLoading || !run) return <Skeleton className="h-40" />;
  return (
    <div className="space-y-4">
      <StepList run={run} threadKey={key} defaultOpen />
      {run.answer && <Card className="p-4"><Markdown text={run.answer} sources={run.sources} /></Card>}
    </div>
  );
}

function StateTimeline({ threadId }: { threadId: string }) {
  const { data: snaps, isLoading } = useThreadStatesQuery(threadId);
  const [i, setI] = useState<number | null>(null);
  const idx = i ?? (snaps ? snaps.length - 1 : 0);
  const current = snaps?.[idx];
  const changed = useMemo(() => {
    if (!snaps || !current) return new Set<string>();
    const prev = (snaps[idx - 1]?.agent_state ?? {}) as Record<string, unknown>;
    return new Set(Object.keys(current.agent_state).filter((k) => JSON.stringify((current.agent_state as Record<string, unknown>)[k]) !== JSON.stringify(prev[k])));
  }, [snaps, current, idx]);

  if (isLoading) return <Skeleton className="h-60" />;
  if (!snaps?.length || !current) return <EmptyState title="No state snapshots yet" />;
  const { messages: _m, ...state } = current.agent_state as Record<string, unknown>; // eslint-disable-line @typescript-eslint/no-unused-vars
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center gap-2">
        <button aria-label="Previous snapshot" disabled={idx === 0} onClick={() => setI(idx - 1)} className="rounded p-1 hover:bg-slate-100 disabled:opacity-30"><ChevronLeft className="h-4 w-4" /></button>
        <input type="range" min={0} max={snaps.length - 1} value={idx} onChange={(e) => setI(Number(e.target.value))} className="flex-1 accent-brand-600" aria-label="State snapshot" />
        <button aria-label="Next snapshot" disabled={idx === snaps.length - 1} onClick={() => setI(idx + 1)} className="rounded p-1 hover:bg-slate-100 disabled:opacity-30"><ChevronRight className="h-4 w-4" /></button>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
        <span>Snapshot {idx + 1} / {snaps.length}</span>
        {current.step != null && <Badge>step {current.step}</Badge>}
        {current.next.length > 0 && <span>next: {current.next.map(label).join(", ")}</span>}
        <span className="ml-auto">{new Date(current.created_at).toLocaleString()}</span>
      </div>
      <p className="mt-2 text-xs text-slate-500">Highlighted keys changed since the previous snapshot.</p>
      <JsonView className="mt-2" value={state} highlight={changed} />
    </Card>
  );
}

export default function HistoryPage() {
  const { conversationId, threadId } = useParams() as { conversationId: string; threadId: string };
  const { data: thread, isLoading } = useThreadQuery(threadId);
  const runs = thread?.runs ?? [];
  const [selected, setSelected] = useState<string | null>(null);
  const runId = selected ?? runs.at(-1)?.id ?? null;
  const [tab, setTab] = useState<"runs" | "state">("runs");

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl space-y-5 px-4 py-6 sm:px-6">
        <div className="flex items-center gap-3">
          <Link to={`/c/${conversationId}/t/${threadId}`} className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100" aria-label="Back to chat"><ArrowLeft className="h-5 w-5" /></Link>
          <div>
            <h1 className="text-lg font-semibold text-slate-900">Thread history</h1>
            <p className="text-sm text-slate-500">{thread?.title ?? "…"} · {runs.length} question{runs.length === 1 ? "" : "s"}</p>
          </div>
          <div className="ml-auto flex rounded-lg border border-slate-200 bg-white p-0.5 text-sm">
            {(["runs", "state"] as const).map((t) => (
              <button key={t} onClick={() => setTab(t)} className={cx("rounded-md px-3 py-1", tab === t ? "bg-brand-50 font-medium text-brand-700" : "text-slate-600")}>
                {t === "runs" ? "Questions & steps" : "AgentState timeline"}
              </button>
            ))}
          </div>
        </div>

        {tab === "state" ? <StateTimeline threadId={threadId} /> : (
          <div className="grid gap-5 lg:grid-cols-[280px_minmax(0,1fr)]">
            <div className="min-w-0 space-y-1">
              {isLoading && <Skeleton className="h-32" />}
              {!isLoading && !runs.length && <EmptyState title="No questions yet" />}
              {runs.map((r) => (
                <button key={r.id} onClick={() => setSelected(r.id)}
                  className={cx("w-full rounded-lg border px-3 py-2 text-left transition", r.id === runId ? "border-brand-300 bg-brand-50/60" : "border-transparent hover:bg-white")}>
                  <div className="line-clamp-2 text-sm text-slate-800">{r.input_type === "voice" && <Mic className="mr-1 inline h-3 w-3" />}{r.question}</div>
                  <div className="mt-1 flex items-center gap-2 text-[11px] text-slate-500">
                    <Badge tone={r.status === "succeeded" ? "green" : r.status === "running" ? "blue" : "amber"}>{r.status}</Badge>
                    {fmt.ago(r.started_at)} · {fmt.secs(r.seconds)}
                  </div>
                </button>
              ))}
            </div>
            <div className="min-w-0">{runId ? <RunReplay key={runId} threadId={threadId} runId={runId} /> : null}</div>
          </div>
        )}
      </div>
    </div>
  );
}
