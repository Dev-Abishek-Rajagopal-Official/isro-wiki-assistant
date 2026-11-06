/** One question + answer: user bubble, live stepper, streamed Markdown answer with citations and sources. */
import { AlertTriangle, ExternalLink, Mic, Rocket } from "lucide-react";
import { Markdown } from "../../components/Markdown";
import { Badge, fmt } from "../../components/ui";
import type { Run, Source } from "../../lib/types";
import type { LiveRun } from "../runs/runsSlice";
import { StepList } from "../steps/StepList";

function SourceCards({ sources }: { sources: Source[] }) {
  const seen = new Set<string>();
  const unique = sources.filter((s) => s.url && !seen.has(s.url) && seen.add(s.url));
  if (!unique.length) return null;
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {unique.slice(0, 6).map((s, i) => (
        <a key={i} href={s.url ?? undefined} target="_blank" rel="noopener noreferrer"
          className="group inline-flex max-w-[260px] items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs text-slate-600 hover:border-brand-300 hover:text-brand-700">
          <span className="flex h-4 min-w-4 items-center justify-center rounded bg-slate-100 px-1 text-[10px] font-semibold text-slate-500 group-hover:bg-brand-100 group-hover:text-brand-700">{s.n ?? i + 1}</span>
          <span className="truncate">{s.title}</span>
          <ExternalLink className="h-3 w-3 shrink-0 opacity-50" />
        </a>
      ))}
    </div>
  );
}

export function Turn({ run, live, threadId }: { run?: Run; live?: LiveRun; threadId: string }) {
  const question = live?.question || run?.question || "";
  const voice = (live?.inputType ?? run?.input_type) === "voice";
  const answer = live?.answer || run?.answer || "";
  const status = live?.status ?? run?.status;
  const streaming = live && (live.status === "running" || live.status === "pending") && !!live.answer;
  const error = live?.error ?? run?.error;

  return (
    <div className="space-y-3">
      {question ? (
        <div className="flex justify-end">
          <div className="max-w-[85%] rounded-2xl rounded-tr-md bg-brand-600 px-4 py-2.5 text-[15px] text-white shadow-sm">
            {voice && <Mic className="mr-1.5 inline h-3.5 w-3.5 opacity-80" aria-label="voice question" />}
            {question}
          </div>
        </div>
      ) : voice && (
        <div className="flex justify-end"><div className="rounded-2xl bg-brand-50 px-4 py-2.5 text-sm text-brand-700"><Mic className="mr-1.5 inline h-3.5 w-3.5" />Transcribing your question…</div></div>
      )}

      <div className="flex gap-3">
        <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-600 text-white"><Rocket className="h-4 w-4" /></div>
        <div className="min-w-0 flex-1 space-y-3">
          {live && <StepList run={live} threadKey={threadId} />}
          {answer && (
            <div>
              <Markdown text={answer} sources={live?.sources} />
              {streaming && <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse rounded-sm bg-brand-500 align-middle" />}
              {live?.sources && live.status === "succeeded" && <SourceCards sources={live.sources} />}
            </div>
          )}
          {status === "failed" && (
            <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>Sorry, this question couldn't be answered{error ? `: ${error}` : "."} Please try again.</span>
            </div>
          )}
          {status === "cancelled" && <Badge tone="slate">Stopped</Badge>}
          {!live && run && run.status === "succeeded" && (
            <div className="text-[11px] text-slate-400">
              {fmt.secs(run.seconds)} · {fmt.compact(run.input_tokens + run.output_tokens)} tokens
              {run.agents_used?.length ? ` · ${run.agents_used.length} agent${run.agents_used.length > 1 ? "s" : ""}` : ""}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
