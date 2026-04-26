# ArsifyOS Browser — MVP

> Brief → PRD + SDD + API Spec, consistency-validated via Marshal engine.

## 🗺 System Map

```
frontend (port 3000)
    ↓ POST /pipeline/run
pipeline_engine (port 8001)
    ↓ marshal.create_session → marshal.run
    ├─ ProductAgent    → prd.md
    ├─ ArchitectAgent  → sdd.md + api_spec.yaml  (retry loop, max 3x)
    └─ ConsistencyEngine → ConsistencyResult (score 0–100)
    ↓ LLM calls
or_gateway / LiteLLM (port 4000)
    ↓ OpenRouter API
Claude Sonnet / GPT-4o
```

**Marshal = Single Source of Truth** — owns all session state and sequencing.  
All output stored in `/pipeline_outputs/{session_id}/` (Docker volume).

## ⚡ One-Command Run

```bash
# 1. Clone / unzip this project
# 2. Set your OpenRouter key
cp .env.example .env
nano .env   # set OPENROUTER_API_KEY

# 3. Run
chmod +x run.sh
./run.sh
```

Open **http://localhost:3000** → paste an idea (50+ chars) → click Run.

## 📦 Project Structure

```
arsify-os/
├── backend/               # Pipeline engine (FastAPI + Marshal)
│   ├── app/
│   │   ├── main.py        # FastAPI entry point
│   │   ├── models/        # Pydantic schemas
│   │   ├── routers/       # /pipeline endpoints
│   │   ├── services/      # Marshal, Agents, ConsistencyEngine, LLMClient
│   │   └── prompts/       # LLM prompt templates
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   └── index.html         # Single-file UI (vanilla JS)
├── infra/
│   └── litellm/
│       └── config.yaml    # LLM routing (no Redis for local dev)
├── tests/                 # Unit + integration + smoke
├── docker-compose.yml
├── run.sh                 # ← START HERE
└── .env.example
```

## 🔌 API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/pipeline/run` | Start pipeline, returns `session_id` |
| `GET`  | `/pipeline/status/{id}` | Poll status |
| `GET`  | `/pipeline/output/{id}` | Get PRD + SDD + API spec |
| `GET`  | `/health` | Healthcheck |

Interactive docs: **http://localhost:8001/docs**

## 🧪 Tests

```bash
pip install -r tests/requirements-test.txt
pytest tests/unit/ -v
```

## 🛑 Stop

```bash
docker-compose down
```
