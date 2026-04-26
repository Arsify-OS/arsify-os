"""
ArchitectAgent — generates SDD and API Spec from PRD content.

SDD responsibility:
  - generate_sdd: one LLM call → sdd.md. On retry: receives prior conflict list.
  - generate_api_spec: one LLM call → api_spec.yaml.

max_tokens per SDD: 4000. per API Spec: 3000 (SDD spec says 3500 — using 3500).
"""

import logging
from pathlib import Path
from typing import Optional

from ..models.schemas import Conflict
from .file_store import FileStore
from .llm_client import LLMClient

logger = logging.getLogger(__name__)

_SDD_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "architect_sdd.txt"
_API_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "architect_api.txt"

# SDD spec table: PRD/SDD=4000, API Spec=3000.
# Using 3500 for API Spec — the YAML openapi: header alone can fill 3000 tokens
# on complex products. Deviation logged in VALIDATION_NOTES.md.
_MAX_TOKENS_SDD = 4000
_MAX_TOKENS_API = 3500
_TIMEOUT        = 120.0


class ArchitectAgent:
    """
    Generates SDD and API Spec from PRD.
    On retry attempts, receives prior conflict list for correction.
    """

    def __init__(self, llm_client: LLMClient, file_store: FileStore):
        self.llm   = llm_client
        self.store = file_store
        self._sdd_template = _SDD_PROMPT_PATH.read_text(encoding="utf-8")
        self._api_template = _API_PROMPT_PATH.read_text(encoding="utf-8")

    # ── SDD generation ────────────────────────────────────────────────────────

    async def generate_sdd(
        self,
        prd_content:        str,
        session_id:         str,
        attempt:            int = 0,
        previous_conflicts: Optional[list[Conflict]] = None,
    ) -> str:
        """
        Generate SDD from PRD.
        On retry (attempt > 0): prior conflicts are embedded in the system prompt.
        Saves sdd.md. Returns content string.
        """
        logger.info(f"[{session_id}] ArchitectAgent: generating SDD (attempt {attempt})")

        conflict_context = self._format_conflicts(previous_conflicts or [])
        system = self._sdd_template.replace("{conflict_context}", conflict_context)

        content = await self.llm.complete(
            system=system,
            user=prd_content,
            max_tokens=_MAX_TOKENS_SDD,
            timeout=_TIMEOUT,
            session_id=session_id,
        )

        self.store.write(session_id, "sdd.md", content)
        logger.info(f"[{session_id}] ArchitectAgent: sdd.md written ({len(content)} chars)")
        return content

    # ── API Spec generation ───────────────────────────────────────────────────

    async def generate_api_spec(
        self,
        prd_content: str,
        sdd_content: str,
        session_id:  str,
        attempt:     int = 0,
    ) -> str:
        """
        Generate OpenAPI 3.0.3 YAML from PRD + SDD.
        Saves api_spec.yaml. Returns content string.
        """
        logger.info(f"[{session_id}] ArchitectAgent: generating API spec (attempt {attempt})")

        # Both PRD and SDD are embedded into the system prompt
        system = (
            self._api_template
            .replace("{prd_content}", prd_content)
            .replace("{sdd_content}", sdd_content)
        )

        content = await self.llm.complete(
            system=system,
            user="Generate the complete OpenAPI 3.0.3 specification based on the PRD and SDD provided.",
            max_tokens=_MAX_TOKENS_API,
            timeout=_TIMEOUT,
            session_id=session_id,
        )

        self.store.write(session_id, "api_spec.yaml", content)
        logger.info(f"[{session_id}] ArchitectAgent: api_spec.yaml written ({len(content)} chars)")
        return content

    # ── Conflict formatter ────────────────────────────────────────────────────

    def _format_conflicts(self, conflicts: list[Conflict]) -> str:
        """
        Converts conflict list into a human-readable block for the SDD retry prompt.
        Returns empty string if no conflicts (first attempt).
        """
        if not conflicts:
            return ""

        lines = [
            "\n\n# PRIOR CONSISTENCY CONFLICTS (MUST FIX)\n",
            "The previous attempt produced these critical conflicts. You MUST resolve all of them:\n",
        ]
        for i, c in enumerate(conflicts, 1):
            lines.append(
                f"\n{i}. [{c.severity.upper()}] {c.type}\n"
                f"   Description:   {c.description}\n"
                f"   PRD reference: {c.prd_reference}\n"
                f"   SDD reference: {c.sdd_reference}\n"
            )
        return "".join(lines)
