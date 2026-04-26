"""
Pipeline router — Phase C: auto-compile + auto-deploy after pipeline success.

Endpoints (unchanged from SDD §4):
  POST /pipeline/run
  GET  /pipeline/status/{session_id}
  GET  /pipeline/output/{session_id}

NEW BEHAVIOUR (Phase C):
  When marshal.run() completes with consistency_score >= 80, the pipeline
  automatically chains:
    pipeline → compile_project → deploy_project
  All three live URLs (status, download, deploy URL) become accessible
  through their respective endpoints — frontend can poll the same /status
  endpoint and discover everything via the augmented session.json fields:
    - compile_status:   "pending" | "running" | "complete" | "failed" | "skipped"
    - deploy_status:    "pending" | "running" | "live"     | "failed" | "skipped"
    - deploy_url:       string when deployed
    - deploy_port:      int

The chain runs as a single BackgroundTask. It NEVER blocks the HTTP request
that started the pipeline.
"""

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from ..models.schemas import (
    OutputBundle,
    PipelineRequest,
    PipelineRunResponse,
    PipelineStatus,
    Session,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/pipeline", tags=["pipeline"])

# ── Consistency gate threshold (mirrors compiler router) ─────────────────────
_AUTO_COMPILE_GATE = 80


# ── Background chain: pipeline → compile → deploy ────────────────────────────

async def _run_full_chain(session_id: str, brief: str, app: Any) -> None:
    """
    BackgroundTask body. Runs marshal.run(), then auto-compile, then auto-deploy.
    Every stage writes its status into session.json via session_manager.update().

    Failure at any stage marks the session in a recoverable state — the
    earlier stages remain valid, and the user can re-trigger via POST /compile
    or POST /deploy/{session_id}.
    """
    marshal  = app.state.marshal
    compiler = app.state.compiler
    deployer = app.state.deployer
    sm       = marshal.session_manager
    fs       = marshal.file_store

    # ── Stage 1: Pipeline (Marshal v1) ────────────────────────────────────────
    try:
        await marshal.run(session_id, brief)
    except Exception as e:
        logger.error(f"[{session_id}] pipeline stage failed: {e}", exc_info=True)
        return

    # Reload state to inspect outcome
    state = sm.get(session_id)
    if state is None or state.status != PipelineStatus.COMPLETE:
        logger.info(
            f"[{session_id}] pipeline did not complete cleanly — "
            f"skipping auto-compile and auto-deploy"
        )
        return

    score = state.consistency_score or 0
    if score < _AUTO_COMPILE_GATE:
        logger.info(
            f"[{session_id}] consistency_score={score} below gate "
            f"{_AUTO_COMPILE_GATE} — skipping auto-compile"
        )
        sm.update(
            session_id, PipelineStatus.COMPLETE,
            compile_status="skipped",
            deploy_status="skipped",
        )
        return

    # ── Stage 2: Auto-compile ─────────────────────────────────────────────────
    sm.update(session_id, PipelineStatus.COMPLETE, compile_status="running")
    try:
        prd      = fs.read(session_id, "prd.md")
        sdd      = fs.read(session_id, "sdd.md")
        api_spec = fs.read(session_id, "api_spec.yaml")

        await compiler.compile_project(
            session_id=session_id, prd=prd, sdd=sdd, api_spec=api_spec,
        )
        logger.info(f"[{session_id}] auto-compile: project.zip generated")
        sm.update(session_id, PipelineStatus.COMPLETE, compile_status="complete")
    except Exception as e:
        logger.error(f"[{session_id}] auto-compile failed: {e}", exc_info=True)
        sm.update(
            session_id, PipelineStatus.COMPLETE,
            compile_status="failed",
            compile_error=str(e),
            deploy_status="skipped",
        )
        return

    # ── Stage 3: Auto-deploy ──────────────────────────────────────────────────
    sm.update(session_id, PipelineStatus.COMPLETE, deploy_status="running")
    try:
        info = deployer.deploy_project(session_id)
        if info.status == "running":
            sm.update(
                session_id, PipelineStatus.COMPLETE,
                deploy_status="live",
                deploy_url=info.url,
                deploy_port=info.port,
                deploy_pid=info.pid,
            )
            logger.info(f"[{session_id}] auto-deploy: LIVE at {info.url}")
        else:
            sm.update(
                session_id, PipelineStatus.COMPLETE,
                deploy_status="failed",
                deploy_error=info.error,
            )
            logger.error(f"[{session_id}] auto-deploy failed: {info.error}")
    except Exception as e:
        logger.error(f"[{session_id}] auto-deploy exception: {e}", exc_info=True)
        sm.update(
            session_id, PipelineStatus.COMPLETE,
            deploy_status="failed",
            deploy_error=str(e),
        )


# ── POST /pipeline/run ────────────────────────────────────────────────────────

@router.post("/run", response_model=PipelineRunResponse, status_code=202)
async def run_pipeline(
    request:          PipelineRequest,
    background_tasks: BackgroundTasks,
    req:              Request,
):
    """
    Start a pipeline session.
    Auto-chains compile + deploy if consistency_score >= 80.
    """
    marshal = req.app.state.marshal
    session_id = marshal.create_session(request.brief)
    background_tasks.add_task(_run_full_chain, session_id, request.brief, req.app)

    logger.info(f"[{session_id}] Pipeline queued (auto-compile + auto-deploy enabled)")
    return PipelineRunResponse(session_id=session_id)


# ── GET /pipeline/status/{session_id} ────────────────────────────────────────

@router.get("/status/{session_id}")
async def get_status(session_id: str, req: Request):
    """
    Return raw session state including new Phase C fields:
    compile_status, deploy_status, deploy_url, deploy_port.

    Returns the underlying session.json dict directly so the frontend can
    read the auto-deploy fields without schema changes upstream.
    """
    marshal = req.app.state.marshal
    if not marshal.file_store.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return marshal.file_store.read_session(session_id)


# ── GET /pipeline/output/{session_id} ────────────────────────────────────────

@router.get("/output/{session_id}", response_model=OutputBundle)
async def get_output(session_id: str, req: Request):
    """Return the OutputBundle (PRD + SDD + API Spec) for a completed session."""
    marshal    = req.app.state.marshal
    file_store = marshal.file_store
    state      = marshal.session_manager.get(session_id)

    if state is None:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    if state.status == PipelineStatus.FAILED:
        raise HTTPException(
            status_code=500,
            detail={"message": "Pipeline failed", "error": state.error},
        )

    if state.status != PipelineStatus.COMPLETE:
        raise HTTPException(
            status_code=404,
            detail={
                "message": "Pipeline not complete",
                "status":  state.status,
                "step":    state.step,
            },
        )

    try:
        outputs = {
            "prd":      file_store.read(session_id, "prd.md"),
            "sdd":      file_store.read(session_id, "sdd.md"),
            "api_spec": file_store.read(session_id, "api_spec.yaml"),
        }
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=f"Output file missing: {exc}")

    return OutputBundle(
        session_id=session_id,
        status=state.status,
        consistency_score=state.consistency_score,
        consistency_result=state.consistency_result,
        outputs=outputs,
    )
