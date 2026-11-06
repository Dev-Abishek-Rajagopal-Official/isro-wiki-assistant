/**
 * Turn a run's timeline into the stepper model shown in the chat and the drawer:
 *   router decision -> agent (rewrite, tool calls, content, LLM calls) -> ... -> final answer,
 * plus a "waiting" row while the router is choosing, so the UI never looks frozen.
 * Pure function: used for live runs and for history (stored events replayed through the same reducer).
 */
import type { LiveRun, TimelineItem } from "../runs/runsSlice";
import type { Source } from "../../lib/types";

export type StepStatus = "waiting" | "running" | "done" | "failed";

export interface ToolCallView {
  id: string;
  tool: string;
  args: unknown;
  status: "running" | "ok" | "empty" | "failed";
  result?: any; // eslint-disable-line @typescript-eslint/no-explicit-any
  error?: string | null;
  durationMs?: number | null;
}

export interface Step {
  id: string;
  kind: "transcribe" | "router" | "agent" | "final" | "waiting";
  node: string;
  title: string;
  detail: string;
  status: StepStatus;
  startedAt?: string;
  endedAt?: string;
  task?: string;
  decision?: Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
  rewrites: { rewritten_query: string; tool_calls: { tool: string; arguments_json: string }[]; retry?: boolean }[];
  tools: ToolCallView[];
  llm: Record<string, any>[]; // eslint-disable-line @typescript-eslint/no-explicit-any
  changes: Record<string, unknown>[];
  content?: string;
  sources?: Source[];
}

export const AGENT_LABELS: Record<string, string> = {
  router: "Router",
  rag_agent: "Knowledge base",
  launch_agent: "Launch schedule",
  wikidata_agent: "Wikidata facts",
  celestrak_agent: "Satellite tracker",
  final_agent: "Final answer",
  title: "Conversation titles",
};
export const AGENT_SOURCES: Record<string, string> = {
  rag_agent: "468 Wikipedia articles (Qdrant hybrid search)",
  launch_agent: "Launch Library 2 (live)",
  wikidata_agent: "Wikidata (structured facts)",
  celestrak_agent: "CelesTrak satellite catalogue (live)",
};
export const label = (node?: string | null) => (node ? AGENT_LABELS[node] ?? node : "");

/** One-line summary of what a tool returned. */
export function summarizeResult(tool: string, result: any): string { // eslint-disable-line @typescript-eslint/no-explicit-any
  if (!result) return "no data";
  const n = (k: string, one: string, many: string) => {
    const v = result[k];
    const c = Array.isArray(v) ? v.length : v && typeof v === "object" ? Object.keys(v).length : 0;
    return `${c} ${c === 1 ? one : many}`;
  };
  if (Array.isArray(result.results)) return n("results", "passage", "passages") + " found";
  if (Array.isArray(result.launches)) return n("launches", "launch", "launches");
  if (Array.isArray(result.missions)) return n("missions", "mission", "missions");
  if (Array.isArray(result.satellites)) return n("satellites", "satellite", "satellites");
  if (Array.isArray(result.matches)) return n("matches", "match", "matches");
  if (result.facts) return n("facts", "fact", "facts");
  if (result.satellite) return `${result.satellite.name ?? "record"} found`;
  if (result.launch) return result.launch.name ?? "launch details";
  if (result.perigee_altitude_km != null) return `orbit ${Math.round(result.perigee_altitude_km)}-${Math.round(result.apogee_altitude_km)} km`;
  if (result.content) return "section loaded";
  return tool;
}

const newStep = (partial: Partial<Step> & Pick<Step, "id" | "kind" | "node" | "title">): Step => ({
  detail: "", status: "running", rewrites: [], tools: [], llm: [], changes: [], ...partial,
});

export function buildSteps(run: LiveRun | undefined): Step[] {
  if (!run) return [];
  const steps: Step[] = [];
  let current: Step | null = null;
  let pendingRouterLlm: Record<string, unknown>[] = [];
  const stepFor = (node: string | null) =>
    current && current.node === node && current.kind !== "router" ? current : [...steps].reverse().find((s) => s.node === node) ?? null;

  if (run.inputType === "voice" && (run.status === "transcribing" || run.transcript)) {
    steps.push(newStep({ id: "transcribe", kind: "transcribe", node: "speech", title: "Speech to text",
      detail: run.transcript ? `"${run.transcript}"` : "Transcribing your voice…",
      status: run.transcript ? "done" : run.status === "failed" ? "failed" : "running" }));
  }

  for (const item of run.timeline as TimelineItem[]) {
    const d = item.data;
    if (item.kind === "llm") {
      if (item.node === "router") pendingRouterLlm.push(d);
      else stepFor(item.node)?.llm.push(d);
      continue;
    }
    if (item.kind === "state") {
      (item.node === "router" ? steps.filter((s) => s.kind === "router").at(-1) : stepFor(item.node))?.changes.push(d);
      continue;
    }
    if (item.kind === "router") {
      if (current && current.status === "running") current.status = "done";
      const next = d.next_agent as string;
      const step = newStep({
        id: item.id, kind: "router", node: "router", status: "done", startedAt: item.ts, endedAt: item.ts,
        title: next === "final_agent" ? "Router: enough information gathered" : `Router → ${label(next)}`,
        detail: next === "final_agent" ? (d.reason ?? "") : (d.task ?? ""), decision: d, llm: pendingRouterLlm,
      });
      pendingRouterLlm = [];
      steps.push(step);
      current = step;
      continue;
    }
    if (item.kind === "error") {
      const target = current ?? steps.at(-1);
      if (target) {
        target.status = "failed";
        target.detail = d.error ?? "failed";
      }
      continue;
    }
    // agent progress
    switch (item.step) {
      case "agent_started": {
        const isFinal = item.node === "final_agent";
        current = newStep({
          id: item.id, kind: isFinal ? "final" : "agent", node: item.node ?? "", startedAt: item.ts,
          title: label(item.node), task: d.task, detail: isFinal ? "Writing the answer…" : "Working…",
        });
        steps.push(current);
        break;
      }
      case "query_rewritten": {
        const s = stepFor(item.node);
        if (s) {
          s.rewrites.push(d as Step["rewrites"][number]);
          s.detail = `Searching: ${d.rewritten_query}`;
        }
        break;
      }
      case "tool_called": {
        const s = stepFor(item.node);
        if (s) {
          let args: unknown = d.arguments;
          try { args = JSON.parse(d.arguments); } catch { /* keep raw */ }
          s.tools.push({ id: item.id, tool: d.tool, args, status: "running" });
          s.detail = `Calling ${d.tool}…`;
        }
        break;
      }
      case "tool_result": {
        const s = stepFor(item.node);
        const call = s?.tools.find((t) => t.tool === d.tool && t.status === "running");
        if (s && call) {
          call.status = !d.ok ? "failed" : d.empty ? "empty" : "ok";
          call.result = d.result;
          call.error = d.error;
          call.durationMs = d.duration_ms;
          call.args = d.arguments ?? call.args;
          s.detail = d.ok ? `${d.tool}: ${summarizeResult(d.tool, d.result)}` : `${d.tool} failed`;
        }
        break;
      }
      case "agent_content": {
        const s = stepFor(item.node);
        if (s) {
          s.status = "done";
          s.endedAt = item.ts;
          s.content = d.content;
          s.sources = d.sources;
          s.detail = `Findings ready · ${d.sources?.length ?? 0} source${d.sources?.length === 1 ? "" : "s"}`;
        }
        break;
      }
    }
  }

  // final answer step state
  const final = steps.find((s) => s.kind === "final");
  if (final) {
    if (run.status === "succeeded") {
      final.status = "done";
      final.detail = `Answer ready · ${run.sources.length} sources`;
      final.endedAt = run.finishedAt;
      final.content = run.answer;
      final.sources = run.sources;
    } else if (run.status === "failed" || run.status === "cancelled") {
      final.status = "failed";
    } else if (run.answer) {
      final.detail = "Writing the answer…";
    }
  }

  // close dangling running steps on terminal states
  if (run.status === "failed" || run.status === "cancelled") {
    steps.filter((s) => s.status === "running").forEach((s) => {
      s.status = "failed";
      s.detail = run.status === "cancelled" ? "Stopped" : run.error ?? s.detail;
    });
  }

  // waiting row while the router is deciding
  const active = run.status === "running" || run.status === "pending";
  const last = steps.at(-1);
  if (active && (!last || (last.status === "done" && last.kind !== "router" && last.kind !== "final"))) {
    steps.push(newStep({ id: "waiting", kind: "waiting", node: "router", status: "running",
      title: "Router", detail: steps.some((s) => s.kind === "agent") ? "Deciding what to do next…" : "Choosing the best source…" }));
  }
  return steps;
}

/** Seconds between two ISO timestamps (null if unknown). */
export function duration(a?: string, b?: string): number | null {
  if (!a || !b) return null;
  return Math.max(0, (new Date(b).getTime() - new Date(a).getTime()) / 1000);
}
