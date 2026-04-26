#!/usr/bin/env bash
# ── ArsifyOS — one-command launcher ─────────────────────────────────────────
# Usage: ./run.sh
# Opens: http://localhost:3000

set -euo pipefail

BOLD="\033[1m"
GREEN="\033[32m"
YELLOW="\033[33m"
RED="\033[31m"
CYAN="\033[36m"
RESET="\033[0m"

log()  { echo -e "${GREEN}[arsify]${RESET} $*"; }
warn() { echo -e "${YELLOW}[arsify]${RESET} $*"; }
err()  { echo -e "${RED}[arsify]${RESET} $*" >&2; }

echo -e "${BOLD}${CYAN}"
echo "  █████╗ ██████╗ ███████╗██╗███████╗██╗   ██╗ ██████╗ ███████╗"
echo " ██╔══██╗██╔══██╗██╔════╝██║██╔════╝╚██╗ ██╔╝██╔═══██╗██╔════╝"
echo " ███████║██████╔╝███████╗██║█████╗   ╚████╔╝ ██║   ██║███████╗"
echo " ██╔══██║██╔══██╗╚════██║██║██╔══╝    ╚██╔╝  ██║   ██║╚════██║"
echo " ██║  ██║██║  ██║███████║██║██║        ██║   ╚██████╔╝███████║"
echo " ╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝╚═╝╚═╝        ╚═╝    ╚═════╝ ╚══════╝"
echo -e "${RESET}"
log "ArsifyOS Browser MVP — starting..."

# ── 1. Check prerequisites ─────────────────────────────────────────────────
for cmd in docker docker-compose curl; do
  if ! command -v "$cmd" &>/dev/null; then
    # try docker compose (v2 plugin)
    if [[ "$cmd" == "docker-compose" ]] && docker compose version &>/dev/null; then
      COMPOSE="docker compose"
      continue
    fi
    err "Required command not found: $cmd"
    err "Install Docker Desktop from https://docs.docker.com/get-docker/"
    exit 1
  fi
done
COMPOSE="${COMPOSE:-docker-compose}"

# ── 2. Check .env ──────────────────────────────────────────────────────────
if [[ ! -f .env ]]; then
  if [[ -f .env.example ]]; then
    warn ".env not found — copying from .env.example"
    cp .env.example .env
    warn "⚠️  EDIT .env and set OPENROUTER_API_KEY before continuing."
    warn "   Get a free key at: https://openrouter.ai/keys"
    echo ""
    read -rp "Press ENTER after editing .env to continue, or Ctrl+C to abort: "
  else
    err ".env file missing. Create one with OPENROUTER_API_KEY and LITELLM_MASTER_KEY."
    exit 1
  fi
fi

# Validate key is set
source .env 2>/dev/null || true
if [[ -z "${OPENROUTER_API_KEY:-}" ]] || [[ "${OPENROUTER_API_KEY}" == sk-or-v1-xxx* ]]; then
  err "OPENROUTER_API_KEY is not set in .env"
  err "Get a free key at: https://openrouter.ai/keys"
  exit 1
fi

log "Environment OK"

# ── 3. Build & start ───────────────────────────────────────────────────────
log "Building pipeline_engine image..."
$COMPOSE build --quiet pipeline_engine

log "Starting all services..."
$COMPOSE up -d

# ── 4. Wait for pipeline_engine health ────────────────────────────────────
log "Waiting for pipeline_engine to be ready..."
MAX_WAIT=90
ELAPSED=0
until curl -sf http://localhost:8001/health >/dev/null 2>&1; do
  if [[ $ELAPSED -ge $MAX_WAIT ]]; then
    err "pipeline_engine did not start within ${MAX_WAIT}s"
    err "Check logs: docker logs arsify_pipeline"
    exit 1
  fi
  sleep 3
  ELAPSED=$((ELAPSED + 3))
  echo -n "."
done
echo ""
log "pipeline_engine ready ✓"

# ── 5. Done ───────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}✅  ArsifyOS is running!${RESET}"
echo ""
echo -e "  ${BOLD}Frontend:${RESET}        http://localhost:3000"
echo -e "  ${BOLD}Pipeline API:${RESET}    http://localhost:8001/docs"
echo -e "  ${BOLD}LLM Gateway:${RESET}     http://localhost:4000/health"
echo ""
echo -e "  ${BOLD}Logs:${RESET}            docker logs -f arsify_pipeline"
echo -e "  ${BOLD}Stop:${RESET}            docker-compose down"
echo ""

# ── 6. Optional: open browser ────────────────────────────────────────────
if command -v open &>/dev/null; then
  open http://localhost:3000
elif command -v xdg-open &>/dev/null; then
  xdg-open http://localhost:3000
fi
