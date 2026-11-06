# ISRO Assistant – frontend

React 19 + TypeScript (strict) + Vite 7 + Tailwind v4, Redux Toolkit + RTK Query, react-router 7, recharts.

## Run

In the full stack (`setup.ps1` / `setup.sh` at the repo root) the app is built into an nginx image
(`Dockerfile`, `nginx.conf`) and served at **http://localhost:3000**; nginx proxies `/api` and the `/api/ws`
WebSocket to the API container. For development with hot reload, run the stack and then:

Prerequisites: the API (`../isro api`, port 8000) and its dependencies (Postgres, Redis, Qdrant, MCP servers) running.

```bash
npm install
npm run dev        # http://localhost:5173 – /api (HTTP + WebSocket) is proxied to :8000
npm test           # vitest unit tests
npm run build      # tsc -b + production bundle in dist/
```

## Structure

| Path | What it does |
|---|---|
| `src/lib/` | HTTP helpers + single-flight token refresh (`api.ts`), token storage, `AgentSocket` WebSocket client (auth, reconnect, resume, dedupe), WAV recorder, shared types |
| `src/services/api.ts` | RTK Query endpoints and cache tags (conversations use `infiniteQuery` cursor paging, 10 per page) |
| `src/app/` | store, typed hooks, router (History / Usage / Admin lazily loaded, Admin behind `RequireAdmin`) |
| `src/features/runs/` | `applyMessage` reducer: folds streamed agent events into a live run per thread |
| `src/features/steps/` | turns a run into stepper rows (`buildSteps`) and the off-canvas drawer (overview, tool calls, findings, LLM calls, state changes) |
| `src/features/socket/` | middleware that wires the socket to Redux and invalidates RTK caches (titles, usage) on server events |
| `src/features/chat`, `conversations`, `history`, `usage`, `admin`, `auth`, `layout` | pages and UI |

## Auth notes

- Access token is kept in memory only; the refresh token is in `localStorage` and rotated on every refresh.
- The admin page is shown only when `/auth/me` returns `is_admin` (server-side `ADMIN_EMAILS`); the admin
  API returns 404 to everyone else. Admin emails are reserved from public sign-up – create the admin account
  with `scripts/create_admin.py` in the API project.
