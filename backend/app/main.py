"""
ArsifyOS — pipeline_engine FastAPI entry point (Phase C: auto-compile + deploy)

Endpoints:
  GET    /health
  POST   /idea
  POST   /pipeline/run                    — auto-chains compile + deploy
  GET    /pipeline/status/{session_id}
  GET    /pipeline/output/{session_id}
  POST   /compile                         — manual trigger (idempotent)
  GET    /compile/download/{session_id}
  POST   /deploy/{session_id}             — manual trigger
  GET    /deploy/{session_id}
  DELETE /deploy/{session_id}
  GET    /deploy/{session_id}/logs
  GET    /deploy/list
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import pipeline_router, compiler_router, idea_router, deploy_router
from .services.marshal_v1_service import MarshalV1
from .services.compiler import Compiler
from .services.deployer import Deployer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

LLM_GATEWAY_URL = os.environ.get("PIPELINE_LLM_GATEWAY", "http://or_gateway:4000")
STORAGE_PATH    = os.environ.get("PIPELINE_STORAGE_PATH", "/pipeline_outputs")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        f"ArsifyOS pipeline_engine starting — "
        f"marshal=v1, gateway={LLM_GATEWAY_URL}, storage={STORAGE_PATH}"
    )
    app.state.marshal = MarshalV1(
        llm_gateway_url=LLM_GATEWAY_URL,
        storage_base=STORAGE_PATH,
    )
    app.state.compiler = Compiler(
        llm_gateway_url=LLM_GATEWAY_URL,
        storage_base=STORAGE_PATH,
    )
    app.state.deployer = Deployer(file_store=app.state.marshal.file_store)
    logger.info("Marshal v1 + Compiler + Deployer wired (auto-chain ENABLED)")
    yield
    logger.info("pipeline_engine shutting down")


app = FastAPI(
    title="ArsifyOS — AI Compiler + Deployer",
    description=(
        "Brief → PRD → EntityManifest → SDD → API Spec → "
        "Consistency Gate → Compiler → ZIP → Auto-Deploy → Live URL"
    ),
    version="4.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)


@app.get("/health", tags=["health"])
async def health():
    return {
        "status":  "ok",
        "service": "pipeline_engine",
        "version": "4.0.0",
        "marshal": "v1_entity_aware",
        "auto_chain": True,
    }


app.include_router(idea_router)
app.include_router(pipeline_router)
app.include_router(compiler_router)
app.include_router(deploy_router)
