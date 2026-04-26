"""
SessionManager — owns the session lifecycle.

All state transitions go through this class.
State is persisted to session.json via FileStore (ADR-001).
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from ..models.schemas import PipelineStatus, Session
from .file_store import FileStore

logger = logging.getLogger(__name__)


class SessionManager:
    """Creates, reads, and updates sessions stored as session.json files."""

    def __init__(self, file_store: FileStore):
        self.store = file_store

    def create(self, brief: str) -> str:
        """Create a new session. Returns session_id (UUID v4)."""
        session_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        data = {
            "session_id":         session_id,
            "brief":              brief,
            "status":             PipelineStatus.QUEUED.value,
            "step":               0,
            "attempt":            0,
            "created_at":         now,
            "updated_at":         now,
            "completed_at":       None,
            "consistency_score":  None,
            "consistency_result": None,
            "error":              None,
        }
        self.store.write_session(session_id, data)
        logger.info(f"[{session_id}] Session created")
        return session_id

    def update(self, session_id: str, status: PipelineStatus, **kwargs: Any) -> None:
        """Update session status and any additional scalar fields."""
        data = self.store.read_session(session_id)
        data["status"] = status.value
        data.update(kwargs)

        if status == PipelineStatus.COMPLETE:
            data["completed_at"] = datetime.now(timezone.utc).isoformat()

        self.store.write_session(session_id, data)
        logger.info(
            f"[{session_id}] Status → {status.value} "
            f"(step={kwargs.get('step', data.get('step'))})"
        )

    def fail(self, session_id: str, error: str) -> None:
        """Mark session as failed and store the error message."""
        data = self.store.read_session(session_id)
        data["status"]       = PipelineStatus.FAILED.value
        data["error"]        = error
        data["completed_at"] = datetime.now(timezone.utc).isoformat()
        self.store.write_session(session_id, data)
        logger.error(f"[{session_id}] Pipeline failed: {error}")

    def get(self, session_id: str) -> Optional[Session]:
        """Return the Session model. None if session does not exist."""
        if not self.store.session_exists(session_id):
            return None
        data = self.store.read_session(session_id)
        return Session(**data)
