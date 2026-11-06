#!/usr/bin/env bash
# Prepares and starts the whole ISRO assistant from scratch (macOS / Linux / WSL), then waits until every
# part is healthy. Same steps as setup.ps1:
#   1 Docker check  2 .env (+ generated local secrets)  3 build images  4 Postgres/Redis/Qdrant
#   5 Wikipedia articles (download only when WIKI_DOWNLOAD=true or --download-wiki, then verify)
#   6 knowledge base in Qdrant (skipped when unchanged)  7 MCP, API, frontend, pgAdmin  8 health check
#
#   ./setup.sh                    # use the committed articles
#   ./setup.sh --download-wiki    # fetch new Wikipedia articles first
#   ./setup.sh --reindex          # rebuild the Qdrant index even if nothing changed
set -euo pipefail
cd "$(dirname "$0")"

DOWNLOAD_WIKI=false
REINDEX=false
for arg in "$@"; do
  case "$arg" in
    --download-wiki) DOWNLOAD_WIKI=true ;;
    --reindex) REINDEX=true ;;
    -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg"; exit 2 ;;
  esac
done

step() { printf '\n\033[36m[%s/8] %s\033[0m\n' "$1" "$2"; }
ok()   { printf '  \033[32mOK\033[0m  %s\n' "$1"; }
die()  { printf '\n  \033[31mFAILED: %s\033[0m\n' "$1"; exit 1; }
secret() { od -An -N32 -tx1 /dev/urandom | tr -d ' \n'; }
env_get() { grep -E "^$1=" .env | tail -n1 | cut -d= -f2- | tr -d '\r' || true; }
env_set() {
  if grep -qE "^$1=" .env; then
    tmp=$(mktemp); awk -v k="$1" -v v="$2" 'BEGIN{FS=OFS="="} $1==k{print k"="v; next} {print}' .env > "$tmp" && mv "$tmp" .env
  else echo "$1=$2" >> .env; fi
}
compose() { docker compose "$@" || die "docker compose $* failed"; }

# ------------------------------------------------------------------------------------------------
step 1 "Checking Docker"
command -v docker >/dev/null || die "Docker is not installed: https://docs.docker.com/get-docker/"
docker info >/dev/null 2>&1 || die "Docker is installed but not running - start it and run this script again."
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required (docker compose ...)."
ok "$(docker --version)"

# ------------------------------------------------------------------------------------------------
step 2 "Configuration (.env)"
if [ ! -f .env ]; then cp .env.example .env; ok "created .env from .env.example"; fi
for k in POSTGRES_PASSWORD REDIS_PASSWORD JWT_SECRET; do
  [ -n "$(env_get "$k")" ] || { env_set "$k" "$(secret)"; ok "generated $k"; }
done
missing=""
for k in LLM_BASE_URL LLM_API_KEY AZURE_OPENAI_ENDPOINT AZURE_OPENAI_API_KEY; do
  v=$(env_get "$k"); { [ -z "$v" ] || [[ "$v" == *"<resource>"* ]]; } && missing="$missing $k"
done
[ -z "$missing" ] || die "fill in these Azure settings in .env, then run again:$missing"
[ -n "$(env_get SPEECH_KEY)" ] || echo "  note: SPEECH_KEY is empty - voice questions are disabled, text chat works"
case "$(env_get WIKI_DOWNLOAD | tr '[:upper:]' '[:lower:]')" in true|1|yes) DOWNLOAD_WIKI=true ;; esac
ok "Azure settings present; WIKI_DOWNLOAD=$DOWNLOAD_WIKI"

# ------------------------------------------------------------------------------------------------
step 3 "Building images (first run takes a few minutes)"
compose --profile jobs build
ok "images built"

# ------------------------------------------------------------------------------------------------
step 4 "Starting Postgres, Redis and Qdrant"
compose up -d --wait postgres redis qdrant
ok "infrastructure healthy"

# ------------------------------------------------------------------------------------------------
step 5 "Wikipedia articles"
PY="/app/isro rag/.venv/bin/python"
if [ "$DOWNLOAD_WIKI" = true ]; then
  echo "  downloading new articles (already downloaded ones are skipped)..."
  compose --profile jobs run --rm wiki
  echo "  checking that every article was downloaded..."
  compose --profile jobs run --rm ingest "$PY" build_knowledge_base.py --verify-docs
  ok "articles downloaded and verified"
else
  echo "  WIKI_DOWNLOAD=false - skipping the download, using the articles in 'wiki documents/'"
  compose --profile jobs run --rm ingest "$PY" build_knowledge_base.py --verify-docs
  ok "articles verified"
fi

# ------------------------------------------------------------------------------------------------
step 6 "Building the knowledge base in Qdrant"
if [ "$REINDEX" = true ]; then compose --profile jobs run --rm ingest "$PY" build_knowledge_base.py --force
else compose --profile jobs run --rm ingest; fi
ok "knowledge base ready"

# ------------------------------------------------------------------------------------------------
step 7 "Starting MCP servers, API, frontend and pgAdmin"
compose up -d --wait mcp api frontend pgadmin
ok "application containers healthy"

# ------------------------------------------------------------------------------------------------
step 8 "Waiting until every dependency reports OK"
FRONT=$(env_get FRONTEND_PORT); FRONT=${FRONT:-3000}
URL="http://localhost:$FRONT/api/health"
status=""
for _ in $(seq 1 60); do
  body=$(curl -s "$URL" || true)
  if echo "$body" | grep -q '"status":"ok"'; then status=ok; break; fi
  sleep 5
done
[ "$status" = ok ] || { echo "$body"; die "not every dependency is healthy - see above and 'docker compose logs api mcp'"; }
ok "database, redis, agent, MCP servers, qdrant, llm, speech"

API=$(env_get API_PORT); QD=$(env_get QDRANT_PORT); PG=$(env_get PGADMIN_PORT)
printf '\n\033[32mISRO assistant is ready.\033[0m\n'
echo "  App        http://localhost:$FRONT          (create an account and ask a question)"
echo "  API docs   http://localhost:${API:-8000}/docs"
echo "  Qdrant     http://localhost:${QD:-6333}/dashboard"
echo "  pgAdmin    http://localhost:${PG:-5050}"
echo
echo "Admin account (emails in ADMIN_EMAILS cannot sign up publicly) - choose its password with:"
echo "  docker compose exec api .venv/bin/python scripts/create_admin.py"
echo "Stop: docker compose stop    |    Remove everything incl. data: docker compose down -v"
