"""
Compiler router — adds the compile layer on top of the existing pipeline.

Endpoints:
  POST /compile                       — trigger compilation for a completed session
  GET  /compile/download/{session_id} — stream project.zip

GAP 5 fix: consistency gate enforced — sessions with score < 80 are blocked.
Marshal and pipeline flow are NOT modified.
"""

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional

from ..models.schemas import PipelineStatus

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/compile", tags=["compiler"])

_CONSISTENCY_GATE = 80


class CompileRequest(BaseModel):
    session_id: str


class CompileResponse(BaseModel):
    status:             str
    download:           str
    consistency_score:  Optional[int] = None


@router.post("", response_model=CompileResponse)
async def compile_project(body: CompileRequest, req: Request):
    """
    Compile a completed pipeline session into a runnable project zip.

    Requirements:
      - Session must exist and be in COMPLETE status.
      - Consistency score must be >= 80 (consistency gate).
    """
    marshal   = req.app.state.marshal
    compiler  = req.app.state.compiler
    session_id = body.session_id

    state = marshal.session_manager.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    if state.status == PipelineStatus.FAILED:
        raise HTTPException(
            status_code=400,
            detail="Cannot compile a failed session. Run the pipeline first.",
        )

    if state.status != PipelineStatus.COMPLETE:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Pipeline must be complete before compiling.",
                "status":  state.status,
                "step":    state.step,
            },
        )

    # ── GAP 5: Consistency gate ───────────────────────────────────────────────
    score = getattr(state, "consistency_score", None)
    if score is not None and score < _CONSISTENCY_GATE:
        raise HTTPException(
            status_code=422,
            detail={
                "message": (
                    f"Consistency score {score}/100 is below the minimum threshold "
                    f"of {_CONSISTENCY_GATE} required for compilation. "
                    "Critical conflicts between PRD, SDD, and API Spec were not resolved. "
                    "Re-run the pipeline with a more detailed brief."
                ),
                "consistency_score": score,
                "threshold":         _CONSISTENCY_GATE,
                "consistency_result": getattr(state, "consistency_result", None),
            },
        )

    # ── Check if already compiled (cache hit) ────────────────────────────────
    file_store = marshal.file_store
    zip_path   = Path(file_store.session_dir(session_id)) / "project.zip"

    if not zip_path.exists():
        try:
            prd      = file_store.read(session_id, "prd.md")
            sdd      = file_store.read(session_id, "sdd.md")
            api_spec = file_store.read(session_id, "api_spec.yaml")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=500, detail=f"Pipeline output file missing: {exc}")

        try:
            await compiler.compile_project(
                session_id=session_id,
                prd=prd,
                sdd=sdd,
                api_spec=api_spec,
            )
        except ValueError as exc:
            logger.error(f"[{session_id}] Compiler validation/parse error: {exc}")
            raise HTTPException(status_code=422, detail=str(exc))
        except Exception as exc:
            logger.error(f"[{session_id}] Compiler failed: {exc}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Compilation failed: {exc}")

    logger.info(f"[{session_id}] Compile complete → /compile/download/{session_id}")
    return CompileResponse(
        status="success",
        download=f"/compile/download/{session_id}",
        consistency_score=score,
    )


@router.get("/download/{session_id}")
async def download_project(session_id: str, req: Request):
    """Stream project.zip for a compiled session."""
    marshal    = req.app.state.marshal
    file_store = marshal.file_store
    zip_path   = Path(file_store.session_dir(session_id)) / "project.zip"

    if not zip_path.exists():
        raise HTTPException(
            status_code=404,
            detail="project.zip not found. Call POST /compile first.",
        )

    return FileResponse(
        path=str(zip_path),
        media_type="application/zip",
        filename=f"arsify-project-{session_id[:8]}.zip",
    )
