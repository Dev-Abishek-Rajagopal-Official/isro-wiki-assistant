# docker – container images

| File | Builds |
|---|---|
| `python.Dockerfile` | every Python component from one recipe; build arg `PROJECT` selects the folder whose `uv.lock` is installed (`isro rag`, `isromcp`, `isro api`). The whole repo is copied because the components import each other by relative path (isromcp → isro rag, isro api → isro agentic orchestration → isromcp/mcp_config.py) |
| `../isro assistant frontend/Dockerfile` | the React app (node build stage) served by nginx, which also proxies `/api` and the WebSocket to the API (`nginx.conf`) |

All services, ports, volumes and health checks are defined in `../docker-compose.yml`; `../setup.ps1` and
`../setup.sh` build and start them in order. Secrets are never copied into images (`../.dockerignore` excludes
every `.env`); they are passed at runtime from the root `.env`.

Useful commands (repo root):

```bash
docker compose ps                       # status + health of every container
docker compose logs -f api mcp          # follow the backend logs
docker compose up -d --build api        # rebuild + restart one service after a code change
docker compose exec api .venv/bin/python scripts/create_admin.py   # create the admin account
docker compose stop                     # stop (data kept in volumes)
docker compose down -v                  # remove containers AND data volumes
```
