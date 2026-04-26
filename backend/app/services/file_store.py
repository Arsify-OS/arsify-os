"""
FileStore — all filesystem I/O for pipeline sessions.

ADR-001: File-based storage. Each session is a directory under /pipeline_outputs.
No database. One method per concern. No logic beyond read/write.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


class FileStore:
    """
    All filesystem I/O for pipeline sessions.
    Stores: session.json, prd.md, sdd.md, api_spec.yaml
    """

    def __init__(self, base_path: str = "/pipeline_outputs"):
        self.base = Path(base_path)
        self.base.mkdir(parents=True, exist_ok=True)

    # ── Path helpers ───────────────────────────────────────────────────────────

    def session_dir(self, session_id: str) -> Path:
        return self.base / session_id

    def ensure_session_dir(self, session_id: str) -> Path:
        path = self.session_dir(session_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    # ── Generic file I/O ───────────────────────────────────────────────────────

    def write(self, session_id: str, filename: str, content: str) -> Path:
        """Write a text file into the session directory."""
        session_dir = self.ensure_session_dir(session_id)
        file_path = session_dir / filename
        file_path.write_text(content, encoding="utf-8")
        logger.debug(f"[{session_id}] Wrote {filename} ({len(content)} chars)")
        return file_path

    def read(self, session_id: str, filename: str) -> str:
        """Read a text file from the session directory. Raises FileNotFoundError if missing."""
        file_path = self.session_dir(session_id) / filename
        return file_path.read_text(encoding="utf-8")

    def exists(self, session_id: str, filename: str) -> bool:
        return (self.session_dir(session_id) / filename).exists()

    def session_exists(self, session_id: str) -> bool:
        return (self.session_dir(session_id) / "session.json").exists()

    # ── session.json ──────────────────────────────────────────────────────────

    def write_session(self, session_id: str, data: dict) -> None:
        """Persist session state as session.json with updated timestamp."""
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.write(session_id, "session.json", json.dumps(data, indent=2, default=str))

    def read_session(self, session_id: str) -> dict:
        """Read and parse session.json."""
        raw = self.read(session_id, "session.json")
        return json.loads(raw)

    # ── Output completeness check ─────────────────────────────────────────────

    def output_files_exist(self, session_id: str) -> bool:
        """True only if all three output documents have been written."""
        return all(
            self.exists(session_id, f)
            for f in ("prd.md", "sdd.md", "api_spec.yaml")
        )

    # ── Session listing ───────────────────────────────────────────────────────

    def list_sessions(self) -> list[str]:
        """Return all session IDs (directory names) under the base path."""
        return [d.name for d in self.base.iterdir() if d.is_dir()]
