/** Types mirroring the isro api responses and WebSocket messages. */

export interface User {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
  is_admin: boolean;
}

export interface ConversationPage {
  items: Conversation[];
  next_cursor: string | null;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface Thread {
  id: string;
  conversation_id: string;
  title: string | null;
  archived: boolean;
  created_at: string;
  updated_at: string;
  last_run_at: string | null;
}

export interface Conversation {
  id: string;
  title: string | null;
  title_source: "generated" | "user" | null;
  archived: boolean;
  created_at: string;
  updated_at: string;
  last_activity_at: string | null;
  thread_count: number;
}

export interface ConversationDetail extends Conversation {
  threads: Thread[];
}

export interface UsageCounts {
  llm_calls: number;
  input_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  cached_tokens: number;
}

export interface Usage extends UsageCounts {
  by_role?: Record<string, UsageCounts>;
  by_model?: Record<string, UsageCounts>;
}

export interface Run {
  id: string;
  thread_id: string;
  question: string;
  input_type: "text" | "voice";
  transcript: { text: string } | null;
  status: "running" | "succeeded" | "failed" | "cancelled";
  answer: string | null;
  agents_used: string[] | null;
  error: string | null;
  started_at: string;
  finished_at: string | null;
  seconds: number | null;
  llm_calls: number;
  input_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  cached_tokens: number;
}

export interface ChatMessage {
  type: "human" | "ai" | string;
  content: string;
}

export const SUB_AGENTS = ["rag_agent", "launch_agent", "wikidata_agent", "celestrak_agent"] as const;
export type SubAgent = (typeof SUB_AGENTS)[number];

export interface Source {
  n?: number;
  agent?: string;
  title: string;
  url?: string | null;
}

/** The orchestrator's AgentState as sent in `state` messages and thread detail. */
export interface AgentState {
  question?: string;
  next_agent?: string;
  task?: string;
  reason?: string;
  rag_agent?: string;
  launch_agent?: string;
  wikidata_agent?: string;
  celestrak_agent?: string;
  final_agent?: string;
  sources?: Record<string, Source[]>;
  visited?: string[];
  hops?: number;
  run_usage?: Usage;
  thread_usage?: Usage;
  messages?: ChatMessage[];
}

export interface ThreadDetail extends Thread {
  messages: ChatMessage[];
  agent_state: AgentState;
  thread_usage: Usage;
  runs: Run[];
}

export interface StoredEvent {
  id: number;
  ts: string;
  thread_id: string;
  run_id: string;
  seq: number;
  node: string | null;
  event_type: string;
  payload: Record<string, unknown>;
}

export interface StateSnapshot {
  checkpoint_id: string;
  created_at: string;
  step: number | null;
  source: string | null;
  next: string[];
  agent_state: AgentState;
}

/** Envelope of every run message on the WebSocket. */
export interface WsMessage {
  type: string;
  thread_id?: string;
  run_id?: string;
  seq?: number;
  node?: string | null;
  event_id?: number | null;
  ts?: string;
  step?: string;
  replay?: boolean;
  client_msg_id?: string;
  data?: any; // eslint-disable-line @typescript-eslint/no-explicit-any
  // conversation_titled
  conversation_id?: string;
  title?: string;
}

export interface UsageGroup extends UsageCounts {
  key: string | null;
  label: string | null;
  total_tokens: number;
  avg_llm_call_seconds: number | null;
}

export interface UsageReport {
  scope: Record<string, string>;
  period_from: string | null;
  period_to: string | null;
  runs: {
    requests: number;
    succeeded: number;
    failed: number;
    cancelled: number;
    voice_requests: number;
    error_rate: number;
    avg_seconds: number | null;
    p50_seconds: number | null;
    p95_seconds: number | null;
  };
  tokens: UsageCounts & { total_tokens: number; avg_llm_call_seconds: number | null };
  group_by: string;
  groups: UsageGroup[];
  latest_rate_limit: { remaining_requests: number | null; remaining_tokens: number | null; observed_at: string | null } | null;
}
