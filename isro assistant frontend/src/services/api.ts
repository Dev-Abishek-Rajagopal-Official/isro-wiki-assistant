/**
 * RTK Query API: every REST call, with request caching and tag-based invalidation.
 *
 * - baseQuery adds the bearer token; on 401 it refreshes the token pair once and retries.
 * - Tags: ConversationList, Conversation, Thread, Runs, Usage, Admin. The socket middleware invalidates them
 *   when the server reports changes (run started/finished, conversation titled).
 * - Immutable history (events, state snapshots of finished runs) is kept 10 minutes; usage/admin 60 s.
 */
import { createApi, fetchBaseQuery, type BaseQueryFn, type FetchArgs, type FetchBaseQueryError } from "@reduxjs/toolkit/query/react";
import { API_BASE, refreshTokens } from "../lib/api";
import { tokens } from "../lib/tokens";
import type {
  Conversation,
  ConversationDetail,
  ConversationPage,
  Run,
  StateSnapshot,
  StoredEvent,
  Thread,
  ThreadDetail,
  TokenPair,
  UsageReport,
  User,
} from "../lib/types";

const rawBaseQuery = fetchBaseQuery({
  baseUrl: API_BASE,
  prepareHeaders: (headers) => {
    if (tokens.access) headers.set("Authorization", `Bearer ${tokens.access}`);
    return headers;
  },
});

const baseQuery: BaseQueryFn<string | FetchArgs, unknown, FetchBaseQueryError> = async (args, api, extra) => {
  let result = await rawBaseQuery(args, api, extra);
  if (result.error?.status === 401 && tokens.refresh && (await refreshTokens())) {
    result = await rawBaseQuery(args, api, extra);
  }
  return result;
};

type Period = { from?: string; to?: string };
const periodParams = (p: Period = {}) => ({ ...(p.from ? { from: p.from } : {}), ...(p.to ? { to: p.to } : {}) });

export const api = createApi({
  reducerPath: "api",
  baseQuery,
  tagTypes: ["Me", "ConversationList", "Conversation", "Thread", "Runs", "Usage", "Admin"],
  endpoints: (build) => ({
    // ---------------------------------------------------------------- auth
    login: build.mutation<TokenPair, { email: string; password: string }>({
      query: (body) => ({ url: "/auth/login", method: "POST", body }),
    }),
    register: build.mutation<User, { email: string; full_name: string; password: string }>({
      query: (body) => ({ url: "/auth/register", method: "POST", body }),
    }),
    logout: build.mutation<void, { refresh_token: string }>({
      query: (body) => ({ url: "/auth/logout", method: "POST", body }),
    }),
    logoutAll: build.mutation<void, void>({ query: () => ({ url: "/auth/logout-all", method: "POST" }) }),
    me: build.query<User, void>({ query: () => "/auth/me", providesTags: ["Me"] }),

    // ---------------------------------------------------------------- conversations (10 per page, "Load more")
    conversations: build.infiniteQuery<ConversationPage, void, string | null>({
      infiniteQueryOptions: {
        initialPageParam: null,
        getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
      },
      query: ({ pageParam }) => ({ url: "/conversations", params: { limit: 10, ...(pageParam ? { cursor: pageParam } : {}) } }),
      providesTags: ["ConversationList"],
    }),
    conversation: build.query<ConversationDetail, string>({
      query: (id) => `/conversations/${id}`,
      providesTags: (_r, _e, id) => [{ type: "Conversation", id }],
    }),
    createConversation: build.mutation<Conversation, { title?: string } | void>({
      query: (body) => ({ url: "/conversations", method: "POST", body: { title: body?.title || null } }),
      invalidatesTags: ["ConversationList"],
    }),
    updateConversation: build.mutation<Conversation, { id: string; title?: string; archived?: boolean }>({
      query: ({ id, ...patch }) => ({ url: `/conversations/${id}`, method: "PATCH", body: patch }),
      invalidatesTags: (_r, _e, { id }) => ["ConversationList", { type: "Conversation", id }],
    }),
    archiveConversation: build.mutation<void, string>({
      query: (id) => ({ url: `/conversations/${id}`, method: "DELETE" }),
      invalidatesTags: ["ConversationList"],
    }),

    // ---------------------------------------------------------------- threads
    createThread: build.mutation<Thread, { conversationId: string; title?: string }>({
      query: ({ conversationId, title }) => ({
        url: `/conversations/${conversationId}/threads`, method: "POST", body: { title: title || null },
      }),
      invalidatesTags: (_r, _e, { conversationId }) => [{ type: "Conversation", id: conversationId }, "ConversationList"],
    }),
    thread: build.query<ThreadDetail, string>({
      query: (id) => `/threads/${id}`,
      providesTags: (_r, _e, id) => [{ type: "Thread", id }],
    }),
    updateThread: build.mutation<Thread, { id: string; conversationId: string; title?: string; archived?: boolean }>({
      query: ({ id, conversationId: _c, ...patch }) => ({ url: `/threads/${id}`, method: "PATCH", body: patch }), // eslint-disable-line @typescript-eslint/no-unused-vars
      invalidatesTags: (_r, _e, { id, conversationId }) => [{ type: "Thread", id }, { type: "Conversation", id: conversationId }],
    }),
    archiveThread: build.mutation<void, { id: string; conversationId: string }>({
      query: ({ id }) => ({ url: `/threads/${id}`, method: "DELETE" }),
      invalidatesTags: (_r, _e, { conversationId }) => [{ type: "Conversation", id: conversationId }],
    }),
    threadRuns: build.query<Run[], string>({
      query: (id) => `/threads/${id}/runs`,
      providesTags: (_r, _e, id) => [{ type: "Runs", id }],
    }),
    threadEvents: build.query<StoredEvent[], { threadId: string; runId?: string }>({
      query: ({ threadId, runId }) => ({ url: `/threads/${threadId}/events`, params: runId ? { run_id: runId } : {} }),
      keepUnusedDataFor: 600,
    }),
    threadStates: build.query<StateSnapshot[], string>({
      query: (id) => `/threads/${id}/states`,
      providesTags: (_r, _e, id) => [{ type: "Runs", id }],
      keepUnusedDataFor: 600,
    }),

    // ---------------------------------------------------------------- usage
    usage: build.query<UsageReport, { groupBy: string } & Period>({
      query: ({ groupBy, ...p }) => ({ url: "/usage/me", params: { group_by: groupBy, ...periodParams(p) } }),
      providesTags: ["Usage"],
      keepUnusedDataFor: 60,
    }),

    // ---------------------------------------------------------------- admin (all users)
    adminOverview: build.query<AdminOverview, Period>({
      query: (p) => ({ url: "/admin/overview", params: periodParams(p) }), providesTags: ["Admin"], keepUnusedDataFor: 60,
    }),
    adminTimeseries: build.query<AdminTimePoint[], Period & { bucket: "hour" | "day" | "week" }>({
      query: ({ bucket, ...p }) => ({ url: "/admin/timeseries", params: { bucket, ...periodParams(p) } }),
      providesTags: ["Admin"], keepUnusedDataFor: 60,
    }),
    adminAgents: build.query<AdminAgents, Period>({
      query: (p) => ({ url: "/admin/agents", params: periodParams(p) }), providesTags: ["Admin"], keepUnusedDataFor: 60,
    }),
    adminTools: build.query<AdminTool[], Period>({
      query: (p) => ({ url: "/admin/tools", params: periodParams(p) }), providesTags: ["Admin"], keepUnusedDataFor: 60,
    }),
    adminModels: build.query<AdminModels, Period>({
      query: (p) => ({ url: "/admin/models", params: periodParams(p) }), providesTags: ["Admin"], keepUnusedDataFor: 60,
    }),
    adminUsers: build.query<{ total: number; items: AdminUserRow[] }, { limit: number; offset: number; search?: string }>({
      query: (params) => ({ url: "/admin/users", params }), providesTags: ["Admin"], keepUnusedDataFor: 60,
    }),
    adminUser: build.query<AdminUserDetail, string>({ query: (id) => `/admin/users/${id}`, keepUnusedDataFor: 60 }),
    adminRuns: build.query<{ total: number; items: AdminRunRow[] }, { status?: string; limit: number; offset: number }>({
      query: ({ status, ...rest }) => ({ url: "/admin/runs", params: { ...rest, ...(status ? { status } : {}) } }),
      providesTags: ["Admin"], keepUnusedDataFor: 60,
    }),
    adminRun: build.query<AdminRunDetail, string>({ query: (id) => `/admin/runs/${id}`, keepUnusedDataFor: 600 }),
    health: build.query<HealthReport, void>({ query: () => "/health", keepUnusedDataFor: 10 }),
  }),
});

// ------------------------------------------------------------------ admin response types
export interface AdminOverview {
  users: { total: number; active_today: number; active_7d: number; active_30d: number };
  conversations: number;
  threads: number;
  runs: UsageReport["runs"];
  tokens: UsageReport["tokens"];
  latest_rate_limit: UsageReport["latest_rate_limit"];
}
export interface AdminTimePoint {
  bucket: string; requests: number; failed: number; error_rate: number; voice: number;
  avg_seconds: number | null; p95_seconds: number | null; llm_calls: number;
  input_tokens: number; output_tokens: number; reasoning_tokens: number;
}
export interface AdminAgents {
  agent_usage: { agent: string; runs: number }[];
  routes: { route: string[]; runs: number; avg_seconds: number | null }[];
  avg_agents_per_run: number | null;
  llm_by_node: { node: string | null; calls: number; tokens: number; avg_seconds: number | null }[];
}
export interface AdminTool {
  agent: string | null; tool: string; calls: number; failed: number; empty: number; failure_rate: number; avg_ms: number | null;
}
export interface AdminModels { by_model: UsageReport["groups"]; by_role: UsageReport["groups"] }
export interface AdminUserRow {
  id: string; email: string; full_name: string; is_active: boolean; created_at: string; last_login_at: string | null;
  conversations: number; requests: number; failed: number; tokens: number; last_active: string | null;
}
export interface AdminUserDetail {
  user: { id: string; email: string; full_name: string; is_active: boolean; created_at: string };
  usage: UsageReport;
  by_role: UsageReport["groups"];
}
export interface AdminRunRow {
  id: string; thread_id: string; conversation_id: string; thread_title: string | null; user_email: string;
  question: string; input_type: string; status: string; error: string | null; started_at: string;
  seconds: number | null; agents_used: string[] | null; tokens: number;
}
export interface AdminRunDetail {
  run: Run & { user_id: string };
  user_email: string | null;
  llm_calls: { node: string; role: string; model: string; input_tokens: number; output_tokens: number; reasoning_tokens: number; cached_tokens: number; seconds: number }[];
  events: { id: number; ts: string; seq: number; node: string | null; event_type: string; payload: Record<string, unknown> }[];
}
export interface HealthReport {
  status: "ok" | "degraded";
  checked_at: number;
  checks: Record<string, { ok: boolean; [k: string]: unknown }>;
}

export const {
  useLoginMutation,
  useRegisterMutation,
  useLogoutMutation,
  useLogoutAllMutation,
  useMeQuery,
  useConversationsInfiniteQuery,
  useConversationQuery,
  useCreateConversationMutation,
  useUpdateConversationMutation,
  useArchiveConversationMutation,
  useCreateThreadMutation,
  useThreadQuery,
  useUpdateThreadMutation,
  useArchiveThreadMutation,
  useThreadRunsQuery,
  useThreadEventsQuery,
  useThreadStatesQuery,
  useUsageQuery,
  useAdminOverviewQuery,
  useAdminTimeseriesQuery,
  useAdminAgentsQuery,
  useAdminToolsQuery,
  useAdminModelsQuery,
  useAdminUsersQuery,
  useAdminUserQuery,
  useAdminRunsQuery,
  useAdminRunQuery,
  useHealthQuery,
} = api;
