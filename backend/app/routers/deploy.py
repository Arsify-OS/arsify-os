"""
Deploy router — exposes the Deployer service over HTTP.

Endpoints:
  POST   /deploy/{session_id}        — start deployment (idempotent)
  GET    /deploy/{session_id}        — get current deployment info
  DELETE /deploy/{session_id}        — stop deployment
  GET    /deploy/{session_id}/logs   — read server.log
  GET    /deploy/list                — list all deployments
"""
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/deploy", tags=["deploy"])


# ── POST /deploy/{session_id} ─────────────────────────────────────────────────

@router.post("/{session_id}")
async def deploy(session_id: str, req: Request) -> dict:
    """
    Start a deployment for a compiled session.
    Idempotent — if already running, returns existing deployment info.
    """
    deployer = req.app.state.deployer
    marshal  = req.app.state.marshal

    # Confirm session exists
    state = marshal.session_manager.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    # Confirm project.zip exists (compile must have happened)
    zip_path = Path(marshal.file_store.session_dir(session_id)) / "project.zip"
    if not zip_path.exists():
        raise HTTPException(
            status_code=400,
            detail="project.zip not found. Call POST /compile first.",
        )

    info = deployer.deploy_project(session_id)

    if info.status == "failed":
        raise HTTPException(
            status_code=500,
            detail={
                "status": "failed",
                "error":  info.error,
                "log":    info.log_path,
            },
        )

    return info.to_dict()


# ── GET /deploy/list ──────────────────────────────────────────────────────────

@router.get("/list")
async def list_deployments(req: Request) -> dict:
    """List all known deployments (running and stopped)."""
    deployer = req.app.state.deployer
    return {
        "count":       len(deployer.list_deployments()),
        "deployments": [d.to_dict() for d in deployer.list_deployments()],
    }


# ── GET /deploy/{session_id} ──────────────────────────────────────────────────

@router.get("/{session_id}")
async def get_deployment(session_id: str, req: Request) -> dict:
    """Get current deployment status for a session."""
    deployer = req.app.state.deployer
    info = deployer.get_deployment(session_id)
    if info is None:
        raise HTTPException(
            status_code=404,
            detail=f"No deployment found for session {session_id}",
        )
    return info.to_dict()


# ── DELETE /deploy/{session_id} ───────────────────────────────────────────────

@router.delete("/{session_id}")
async def stop_deployment(session_id: str, req: Request) -> dict:
    """Stop a running deployment."""
    deployer = req.app.state.deployer
    stopped = deployer.stop_deployment(session_id)
    if not stopped:
        raise HTTPException(
            status_code=404,
            detail=f"No active deployment for session {session_id}",
        )
    return {"status": "stopped", "session_id": session_id}


# ── GET /deploy/{session_id}/logs ─────────────────────────────────────────────

@router.get("/{session_id}/logs")
async def get_logs(session_id: str, req: Request, tail: int = 200) -> dict:
    """Return last `tail` lines of the deployed app's server.log."""
    deployer = req.app.state.deployer
    info = deployer.get_deployment(session_id)
    if info is None:
        raise HTTPException(
            status_code=404,
            detail=f"No deployment found for session {session_id}",
        )
    if not info.log_path:
        return {"session_id": session_id, "log": "", "lines": 0}

    try:
        lines = Path(info.log_path).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return {"session_id": session_id, "log": "", "lines": 0}

    snippet = lines[-tail:] if tail else lines
    return {
        "session_id":  session_id,
        "log":         "\n".join(snippet),
        "lines":       len(snippet),
        "total_lines": len(lines),
    }
