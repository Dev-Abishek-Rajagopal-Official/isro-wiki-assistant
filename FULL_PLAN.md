# ISRO Assistant – full plan (backend additions + frontend)

Goal: a chat app where any user can ask about ISRO by **text or voice**, watch every **agent step live**, open any
step to see **exactly what each API / tool / chunk / LLM call returned**, revisit conversations and threads, and see
usage. One admin (`official@abishekrajagopal.com`) gets an **admin panel** with system-wide analytics.

---

## 1. System overview

```
Browser (React + TS + Tailwind + Redux Toolkit)
  │  REST  /api/*  (Bearer JWT)            WebSocket /api/ws (auth message first)
  ▼                                         ▼
isro api  (FastAPI :8000) ── auth · conversations · threads · history · usage · admin · health · ws hub
  ├── LangGraph agent (isro agentic orchestration): router → rag / launch / wikidata / celestrak → final
  │      └── MCP servers (isromcp :8101-8104, HTTP) → Qdrant (RAG) · Launch Library 2 · Wikidata · CelesTrak
  ├── Azure AI Foundry (gpt-6-luna, text-embedding-3-large) · Azure Speech (speech-to-text)
  ├── PostgreSQL :5432  (app tables, agent_events, llm_calls, LangGraph checkpoints)   pgAdmin :5050
  └── Redis :6379       (token store, caches, run/title locks, WebSocket pub/sub)
```

| Status | Part |
|---|---|
| ✅ done, tested | data pipeline, RAG + evals, 4 MCP servers, LangGraph agent, FastAPI (auth, conversations/threads, WebSocket, history, usage), Postgres + Redis; 67/67 tests |
| ✅ done | frontend foundation: Vite/TS/Tailwind config, API types, REST client (refresh), WebSocket client (reconnect/resume/dedupe), run reducer, voice→WAV encoder |
| ⬜ to do | backend additions (§3), all frontend screens (§7–§9), admin panel, tests, README |

---

## 2. Agent state (what the UI visualises)

`AgentState` (LangGraph TypedDict, persisted per thread by the Postgres checkpointer):

| Field | Meaning |
|---|---|
| `messages` | conversation turns of the thread (memory) |
| `question` | current question (typed or transcribed) |
| `next_agent`, `task`, `reason` | router's structured decision |
| `rag_agent`, `launch_agent`, `wikidata_agent`, `celestrak_agent` | content each sub-agent generated ("" = not called) |
| `final_agent` | final answer |
| `sources` | per agent: title, url, … |
| `visited`, `hops` | agents used this question, hop count (max 5) |
| `run_usage` / `thread_usage` | tokens this question / thread lifetime; totals + `by_role` + `by_model` |

Every change is (a) written to `agent_events` (ordered, per run) and (b) pushed over the WebSocket
(`state_update` delta + `state` full snapshot), so the UI and the database show the same sequence.

---

## 3. Backend additions (before the UI)

1. **Tool return data in events** – `tool_result` gets `result` (the MCP tool's JSON: RAG chunks, launches,
   facts, satellite record) capped at ~12 KB per call, plus `duration_ms`. Stored → History shows it too.
   (LLM *prompts* stay out by default; outputs + stats are already recorded. Optional debug flag later.)
2. **Cursor pagination for conversations** – `GET /conversations?limit=10&cursor=<opaque>` →
   `{items, next_cursor}`, ordered by `(last_activity_at, id)`; stable while conversations move to the top.
3. **Admin role**
   - `ADMIN_EMAILS=official@abishekrajagopal.com` in the API `.env`; `GET /auth/me` returns `is_admin`.
   - **Registration refuses admin emails** (no email verification exists, so otherwise anyone could claim it);
     the admin account is created with `uv run python scripts/create_admin.py` (password prompted, not stored).
   - `require_admin` dependency on every `/admin/*` route; non-admins get **404** (page not revealed).
4. **Admin endpoints** (all users, `from`/`to` filters, Redis-cached 60 s)

| Endpoint | Returns |
|---|---|
| `GET /admin/overview` | users total / active today / 7 days, conversations, threads, requests, success & error rate, voice share, p50/p95 latency, tokens (in/out/reasoning/cached), latest rate-limit headroom |
| `GET /admin/timeseries?metric=requests|tokens|errors|latency&bucket=day|hour` | series for charts |
| `GET /admin/agents` | usage per agent, common routes (e.g. rag→final), average hops |
| `GET /admin/tools` | calls per MCP tool, failure rate, average duration (from `tool_result`) |
| `GET /admin/models` | tokens and calls per model and LLM role |
| `GET /admin/users?cursor=` | per user: conversations, requests, tokens, last active |
| `GET /admin/users/{id}` | one user's usage breakdown |
| `GET /admin/runs?status=failed&cursor=` | recent failed / cancelled runs with errors |
| `GET /admin/runs/{id}` | any run with its full event timeline (debugging) |

5. **Tests**: tool-result payload + cap, cursor paging (no duplicates/skips), admin-email registration block,
   admin 404 for normal users, admin aggregates on seeded data.

---

## 4. Storage and caching

**PostgreSQL**: `users` · `conversations` (LLM title, `title_source`, timestamps, `last_activity_at`) · `threads`
(= LangGraph thread_id) · `runs` (status, answer, agents, seconds, token totals) · `llm_calls` (role, model, tokens,
latency, rate-limit headroom) · `agent_events` (every state change / progress event, now incl. tool results) ·
LangGraph checkpoint tables (AgentState snapshot per step).

**Redis**: refresh tokens + access revocation · `lock:run:{thread}` · `lock:title:{conversation}` · pub/sub
`ws:thread:*`, `ws:user:*` · caches below.

| Cache | Where | TTL / invalidation |
|---|---|---|
| user lookup | Redis | 5 min |
| usage reports | Redis | 60 s |
| admin analytics | Redis | 60 s |
| health | Redis | 10 s |
| conversations list | RTK Query | until `run_started` / `conversation_titled` / create / rename / archive |
| thread detail, runs | RTK Query | invalidated on `run_finished` of that thread |
| events / state snapshots of finished runs | RTK Query | immutable → kept 10 min |
| usage / admin | RTK Query | 60 s (matches server) |

---

## 5. API contract used by the frontend (all via `/api`)

**REST**

| Area | Endpoints |
|---|---|
| Auth | `POST /auth/register` · `POST /auth/login` · `POST /auth/refresh` (rotating) · `POST /auth/logout` · `POST /auth/logout-all` · `GET /auth/me` (+ `is_admin`) |
| Conversations | `GET /conversations?limit=10&cursor=` · `POST /conversations` · `GET/PATCH/DELETE /conversations/{id}` |
| Threads | `POST/GET /conversations/{id}/threads` · `GET/PATCH/DELETE /threads/{id}` (detail = messages, AgentState, usage, runs) |
| History | `GET /threads/{id}/runs` · `GET /threads/{id}/events?after_id=` · `GET /threads/{id}/states` · `GET /runs/{id}` |
| Ask (fallback) | `POST /threads/{id}/ask` · `POST /threads/{id}/ask-audio` |
| Usage | `GET /usage/me` · `/usage/conversations/{id}` · `/usage/threads/{id}` |
| Admin | §3.4 |
| Health | `GET /health` |

**WebSocket `/api/ws`** – one socket per tab, many threads.

```
→ {"type":"auth","token":JWT}                         ← auth_ok | auth_failed (close 4401)
→ {"type":"ask","thread_id","question","client_msg_id"}          ← accepted {run_id}
→ {"type":"ask_audio","thread_id","audio_b64","filename","content_type","client_msg_id"}
→ {"type":"subscribe","thread_id","after_id"}         ← subscribed, replayed events (replay:true), replay_done
→ {"type":"unsubscribe","thread_id"}  → {"type":"cancel","run_id"}  → {"type":"ping"}
```

Run messages share `{type, thread_id, run_id, seq, node, event_id, ts, step?, data}`:
`run_started` · `transcribing` · `transcribed` · `router_decision` · `agent_progress` (step = agent_started /
query_rewritten / tool_called / tool_result / agent_content) · `llm_call` · `state_update` · `state` · `token` ·
`final_answer` · `run_finished` · `run_cancelled` · `error` · `busy`; user-level: `conversation_titled`.

Client rules: authenticate first; on `auth_expired` refresh + re-auth; on disconnect reconnect with backoff and
`subscribe` each followed thread with its last `event_id`; de-duplicate by `event_id`.

**Connection and group model (decided)**

| Concept | ID | Role in real-time delivery |
|---|---|---|
| user | `users.id` | authenticates the socket; every socket joins `ws:user:{user_id}` (e.g. `conversation_titled`) |
| conversation | `conversations.id` | container for threads; **no channel of its own** (not needed while one thread is shown at a time) |
| thread | `threads.id` | the "session": LangGraph `thread_id` (memory + AgentState), run-lock key, and group `ws:thread:{thread_id}` |
| run | `runs.id` | tags every event of one question |

One WebSocket per browser tab; it joins a thread's channel only after an ownership check (`ask` or `subscribe`).
Several tabs/devices on the same thread all receive the run live; Redis pub/sub makes it work across API instances.
A per-conversation channel is only worth adding with shared conversations (§14).

---

## 6. Event → UI step mapping (live stepper)

| Event | UI |
|---|---|
| `ask` sent | user bubble + "Sending…" |
| `transcribing` / `transcribed` | "Transcribing your voice…" → transcript becomes the user bubble |
| `run_started` | stepper appears; pending row "Router is choosing an agent…" ⟳ |
| `router_decision` | ✓ Router → "asked *Launch agent*: find the next ISRO launch" |
| `agent_progress: agent_started` | ⟳ agent row, e.g. "Launch agent – working…" |
| `query_rewritten` | sub-row ✓ "Rewrote query: …" |
| `tool_called` → `tool_result` | sub-row ⟳ "Calling upcoming_isro_launches…" → ✓ "1 launch returned · 0.4 s" (⚠ on error/empty) |
| `agent_content` | ✓ agent row "Findings ready (n sources)"; pending row "Router is deciding…" |
| `agent_started final_agent` + `token`s | ⟳ "Writing answer…" while text streams |
| `final_answer` / `run_finished` | ✓; stepper collapses: "4 steps · 3 agents · 12.4 s · 4.1k tokens" |
| `error` / `run_cancelled` | ⚠ on the active row, message shown, composer re-enabled |

Durations come from event timestamps; every row is clickable → details drawer.

---

## 7. Frontend architecture

**Stack**: React 19 + TypeScript (strict) · Vite · Tailwind CSS 4 (+ typography) · **Redux Toolkit + RTK Query** ·
React Router 7 · react-markdown + remark-gfm · Recharts · lucide-react icons · Vitest + Testing Library · Playwright smoke.

```
isro web/src/
  app/          store.ts (configureStore) · hooks.ts (typed useAppDispatch/useAppSelector) · router.tsx
  lib/          types.ts · tokens.ts · ws.ts · audio.ts            (done)
  services/     api.ts – RTK Query createApi (baseQuery with bearer + refresh-and-retry), endpoints, tags
  features/
    auth/       authSlice · LoginPage · RegisterPage · RequireAuth · RequireAdmin
    socket/     socketMiddleware (WS ↔ Redux; cache invalidation)
    runs/       runsSlice (live runs; reducer done) · stepsSelectors (events → stepper model)
    conversations/  Sidebar · ConversationItem · ThreadList · LoadMore
    chat/       ChatPage · MessageList · UserBubble · AnswerView · Citations · SourceCards · Composer · VoiceButton
    steps/      StepList · StepRow · StepDrawer · panels/ (Router, SubAgent, ToolCall, Final, RunSummary, AgentStateTree)
    history/    HistoryPage · Timeline · StateSlider
    usage/      UsagePage · KpiCards · Charts
    admin/      AdminPage · Overview · Timeseries · Agents · Tools · Models · Users · Errors · SystemHealth
  components/   Drawer · Tabs · JsonView · Markdown · Spinner · Badge · Button · Input · Menu · Toast · EmptyState · Skeleton
```

**Redux store**

| Slice | State |
|---|---|
| `auth` | user (incl. `is_admin`), status; access token in memory, refresh token in localStorage |
| `runs` | per thread: live run (status, question, streamed answer, timeline, AgentState, usage, sources) |
| `socket` | connection status, followed threads |
| `ui` | sidebar collapsed, drawer `{open, threadId, stepId}`, toasts |
| `api` (RTK Query) | cached REST data; tags `Conversation`, `ConversationList`, `Thread`, `Runs`, `Usage`, `Admin` |

**Socket middleware**: starts the socket after login, stops on logout; dispatches every message into `runs`;
`conversation_titled` / `run_started` → invalidate `ConversationList`; `run_finished` → invalidate `Thread`,
`Runs`, `Usage`; follows the open thread (subscribe with resume).

**Routing**: `/login`, `/register` · `/` (chat, empty state) · `/c/:conversationId/t/:threadId` (chat) ·
`/c/:conversationId/t/:threadId/history` · `/usage` · `/admin` (RequireAdmin) · 404.

---

## 8. Screens and UX

**Design**: clean, light theme, slate neutrals + one brand blue, generous spacing, readable 15–16 px text, clear
loading/empty/error states everywhere, responsive (sidebar collapses, drawer full-screen on mobile),
keyboard-accessible (focus trap, Esc, visible focus), `aria-live` for streaming status.

1. **Sign in / Sign up** – centred card, inline validation, friendly errors, "show password".
2. **Top bar** – app name · connection dot · **Usage** · **Admin** (only `is_admin`) · user menu (logout, logout everywhere).
3. **Sidebar** – "+ New conversation"; **10 most recent conversations** (title, relative time) + **Load more**
   (next 10, hidden when none left); open conversation expands its threads + "+ New thread"; ⋯ rename / archive;
   titles update live.
4. **Chat** – messages; under each user question the live **stepper** (§6), then the answer (Markdown, citation
   chips `[n]` with hover title, source cards); thread header shows title + live thread token count.
   **Composer**: textarea (Enter send, Shift+Enter newline) + 🎤 (record timer → "Transcribing…") + Stop while running;
   example-question chips on empty threads; one active run per thread (busy message otherwise).
5. **Details drawer** (click any step)

| Step | Tabs |
|---|---|
| Router | Decision (next agent, task, reason, guardrail override) · Structured block (next_agent + every agent's content) · LLM call |
| Sub-agent | Overview (task, rewritten query) · **Tool calls** (args, status, duration, **returned data**: RAG chunk cards with article › section, score, text, link; launches table; Wikidata facts; CelesTrak record/orbit; Raw JSON + copy) · Generated content · LLM calls (rewriter + generator: model, tokens, latency) |
| Final | Answer · numbered sources · LLM call |
| Run summary | time, agents, tokens by role/model, rate-limit headroom |
| any | **AgentState** tree with just-changed fields highlighted |

6. **History** – past runs list; selecting one rebuilds its stepper from stored events (same drawer);
   **AgentState snapshot slider** steps through every checkpoint.
7. **Usage (mine)** – KPI cards + charts by day / model / role / agent / conversation.
8. **Admin** – tabs: Overview · Trends · Agents & routes · Tools (MCP) · Models & roles · Users · Errors · System;
   date-range picker; clicking a failed run opens its timeline.

---

## 9. Voice flow

🎤 → browser asks microphone permission → MediaRecorder → on stop: decode + resample to **16 kHz mono WAV** →
base64 → `ask_audio` over the WebSocket → server Azure Fast Transcription (ISRO phrase list) → `transcribed`
(shown as the user's message) → same agent run. Limits: 25 MB; clear errors for denied mic / no speech.

---

## 10. Security

JWT access 8 h (memory) + rotating refresh 7 d (localStorage; httpOnly cookie = future hardening) · logout and
logout-everywhere revoke in Redis · server-side ownership checks (404 for others' data) · admin enforced server-side,
admin email reserved, account created by CLI · WebSocket auth by first message (no token in URL) · Markdown rendered
without raw HTML · external links `rel="noopener noreferrer"`.

---

## 11. Testing and verification

| Layer | Tests |
|---|---|
| Backend | new: tool-result payload/cap, cursor paging, admin access + aggregates, admin-email block; existing 67 keep passing |
| Frontend unit (Vitest) | runs reducer, steps selector (events → stepper), WAV encoder, base query refresh-and-retry, socket middleware invalidation |
| Components | StepList states, StepDrawer panels, Sidebar Load more, RequireAdmin |
| E2E (Playwright smoke) | sign up → ask → steps → drawer shows RAG chunks → answer; admin nav hidden for normal user |
| Manual in browser (live backend) | text + voice question, live steps, drawer data, history replay, usage, admin panel |

---

## 12. Build order (milestones)

1. **Backend**: tool_result data · cursor paging · is_admin + reserved email + `create_admin.py` · `/admin/*` + Redis cache · tests
2. **Frontend foundation**: Redux store, RTK Query API + base query, socket middleware, runs slice (port reducer)
3. Auth pages, layout, top bar, route guards
4. Sidebar (10 + Load more, threads, rename/archive)
5. Chat: messages, answer view, citations, composer (text + voice)
6. Live stepper + details drawer (all panels)
7. History (timeline + state slider)
8. Usage page
9. Admin panel
10. Tests, browser verification, README

## 13. Open items / risks

- Latency 10–30 s per question with gpt-6-luna for every role → the live stepper makes waiting visible; a faster
  model for router/rewriters is a one-line `MODEL_<ROLE>` change.
- Refresh token in localStorage (XSS exposure) – documented; cookie-based refresh is the hardening step.
- Azure key pasted in chat earlier – rotate before submission.
- Git not installed on this machine – needed for the GitHub submission.

## 14. Future (not in this build)

**Shared conversations** – add other users to a conversation so they see its full history and live runs.
- `conversation_members` (conversation, user, role owner / editor / viewer, added_by, added_at).
- Access checks change from "owns" to "is a member" (one place: `repository.py` + the socket's thread check).
- Viewers read + watch live; editors can also ask; owners manage members, rename, archive.
- Invite by email (registered users), optional expiring share link; remove member / leave.
- Sidebar "Shared with me"; "X is asking…" indicator; events show who asked.
- Add `ws:conversation:{id}` channel so members see new threads / titles live.
- Already supported: runs and llm_calls record who asked (usage stays per person), full stored history,
  per-thread run lock prevents simultaneous asks. Decide then: shared thread memory (default) vs. own threads.
