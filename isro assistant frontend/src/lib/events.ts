/** Stored events (GET /threads/{id}/events, admin run detail) -> the same message shape the WebSocket sends. */
import type { WsMessage } from "./types";

const PROGRESS_STEPS = new Set(["agent_started", "query_rewritten", "tool_called", "tool_result", "agent_content"]);

export interface StoredLike {
  id: number;
  ts: string;
  seq: number;
  node: string | null;
  event_type: string;
  payload: Record<string, unknown>;
  run_id?: string;
}

export function storedToMessage(e: StoredLike, threadKey: string): WsMessage {
  const isStep = PROGRESS_STEPS.has(e.event_type);
  return {
    type: isStep ? "agent_progress" : e.event_type,
    step: isStep ? e.event_type : undefined,
    thread_id: threadKey, run_id: e.run_id, seq: e.seq, node: e.node, event_id: e.id, ts: e.ts, data: e.payload,
    replay: true,
  };
}
