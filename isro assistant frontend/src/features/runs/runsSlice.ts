/**
 * Live run state per thread, built from WebSocket messages by a pure reducer (`applyMessage`).
 * Keeps the latest run of each thread: question, streamed answer, timeline of agent events, current
 * AgentState, token usage, sources and status. History replays stored events through the same reducer.
 */
import { createSlice, type PayloadAction } from "@reduxjs/toolkit";
import type { AgentState, Source, Usage, WsMessage } from "../../lib/types";

export type RunStatus = "pending" | "transcribing" | "running" | "succeeded" | "failed" | "cancelled";

export interface TimelineItem {
  id: string;
  kind: "router" | "step" | "llm" | "state" | "error";
  node: string | null;
  step?: string;
  data: Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
  ts?: string;
}

export interface LiveRun {
  runId: string | null;
  clientMsgId?: string;
  status: RunStatus;
  question: string;
  inputType: "text" | "voice";
  transcript?: string;
  answer: string;
  sources: Source[];
  timeline: TimelineItem[];
  agentState: AgentState | null;
  prevAgentState: AgentState | null;
  runUsage: Usage | null;
  threadUsage: Usage | null;
  agentsUsed: string[];
  seconds: number | null;
  startedAt?: string;
  finishedAt?: string;
  error?: string;
}

export const emptyRun = (question = "", inputType: "text" | "voice" = "text"): LiveRun => ({
  runId: null, status: "pending", question, inputType, answer: "", sources: [], timeline: [], agentState: null,
  prevAgentState: null, runUsage: null, threadUsage: null, agentsUsed: [], seconds: null,
});

let counter = 0;
const itemId = (msg: WsMessage) => (msg.event_id != null ? `e${msg.event_id}` : `l${++counter}`);
const push = (run: LiveRun, item: TimelineItem): LiveRun => ({ ...run, timeline: [...run.timeline, item] });

/** Pure: the live run after one message (same object if the message does not change it). */
export function applyMessage(run: LiveRun | undefined, msg: WsMessage): LiveRun | undefined {
  const d = msg.data ?? {};
  switch (msg.type) {
    case "accepted":
      return run ? { ...run, runId: msg.run_id ?? run.runId } : run;
    case "transcribing":
      return { ...(run ?? emptyRun("", "voice")), runId: msg.run_id ?? run?.runId ?? null, status: "transcribing", inputType: "voice" };
    case "transcribed":
      return run ? { ...run, transcript: d.text, question: d.text } : run;
    case "run_started": {
      const same = run && (run.runId === msg.run_id || (run.runId === null && run.status === "pending") ||
        (run.status === "transcribing" && (!run.runId || run.runId === msg.run_id)));
      const base = same && run ? run : emptyRun();
      return {
        ...base, runId: msg.run_id ?? null, status: "running", question: d.question ?? base.question,
        inputType: d.input_type ?? base.inputType, transcript: d.transcript?.text ?? base.transcript,
        answer: "", timeline: [], sources: [], startedAt: msg.ts, error: undefined,
      };
    }
    case "router_decision":
      return run && push(run, { id: itemId(msg), kind: "router", node: "router", data: { ...d.structured, overridden: d.overridden, model_choice: d.model_choice, seconds: d.seconds }, ts: msg.ts });
    case "agent_progress":
      return run && push(run, { id: itemId(msg), kind: "step", node: msg.node ?? null, step: msg.step, data: d, ts: msg.ts });
    case "llm_call":
      return run && push(run, { id: itemId(msg), kind: "llm", node: msg.node ?? null, data: d, ts: msg.ts });
    case "state_update": {
      // keep what each node changed; also fold the changes into agentState (History has no full snapshots)
      if (!run) return run;
      const changes = (d.changes ?? {}) as Record<string, unknown>;
      const folded = { ...(run.agentState ?? {}) } as Record<string, unknown>;
      for (const [k, v] of Object.entries(changes)) {
        if (k !== "run_usage" && k !== "thread_usage" && k !== "messages") folded[k] = v;
      }
      return push({ ...run, agentState: folded as AgentState },
        { id: itemId(msg), kind: "state", node: msg.node ?? null, data: changes, ts: msg.ts });
    }
    case "state":
      return run && {
        ...run, prevAgentState: run.agentState, agentState: d.agent_state,
        runUsage: d.agent_state?.run_usage ?? run.runUsage, threadUsage: d.agent_state?.thread_usage ?? run.threadUsage,
      };
    case "token":
      return run && { ...run, answer: run.answer + (d.text ?? "") };
    case "final_answer":
      return run && { ...run, answer: d.answer ?? run.answer, sources: d.sources ?? [] };
    case "run_finished":
      return run && {
        ...run, status: run.status === "failed" || run.status === "cancelled" ? run.status : "succeeded",
        seconds: d.seconds ?? null, agentsUsed: d.agents_used ?? [], finishedAt: msg.ts,
        runUsage: d.run_usage ?? run.runUsage, threadUsage: d.thread_usage ?? run.threadUsage,
      };
    case "run_cancelled":
      return run && { ...run, status: "cancelled" };
    case "error":
      return run && push({ ...run, status: "failed", error: d.error ?? "Something went wrong" },
        { id: itemId(msg), kind: "error", node: msg.node ?? null, data: d, ts: msg.ts });
    case "busy":
      return run && { ...run, status: "failed", error: d.error ?? "This thread is busy" };
    default:
      return run;
  }
}

interface RunsState {
  byThread: Record<string, LiveRun>;
}

const initialState: RunsState = { byThread: {} };

const runsSlice = createSlice({
  name: "runs",
  initialState,
  reducers: {
    /** Optimistic entry when the user sends a question (before the server confirms). */
    started(state, action: PayloadAction<{ threadId: string; question: string; inputType: "text" | "voice"; clientMsgId: string }>) {
      const { threadId, question, inputType, clientMsgId } = action.payload;
      state.byThread[threadId] = { ...emptyRun(question, inputType), clientMsgId,
        status: inputType === "voice" ? "transcribing" : "pending" };
    },
    messageReceived(state, action: PayloadAction<WsMessage>) {
      const tid = action.payload.thread_id;
      if (!tid) return;
      const next = applyMessage(state.byThread[tid] as LiveRun | undefined, action.payload);
      if (next) state.byThread[tid] = next;
    },
    cleared(state, action: PayloadAction<string>) {
      delete state.byThread[action.payload];
    },
    reset: () => initialState,
  },
});

export const runsActions = runsSlice.actions;
export default runsSlice.reducer;
