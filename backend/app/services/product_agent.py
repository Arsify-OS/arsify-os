"""
ProductAgent — generates the PRD from the user's brief.

SDD responsibility: one LLM call → one file written (prd.md).
No decision logic. No retry awareness. Receives brief, returns PRD content.
"""

import logging
from pathlib import Path

from .file_store import FileStore
from .llm_client import LLMClient

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "product_prd.txt"

# SDD: max_tokens = 4000 for PRD
_MAX_TOKENS = 4000
_TIMEOUT    = 120.0


class ProductAgent:
    """Generates PRD from brief. Single responsibility: one LLM call, one file."""

    def __init__(self, llm_client: LLMClient, file_store: FileStore):
        self.llm        = llm_client
        self.store      = file_store
        self._system    = _PROMPT_PATH.read_text(encoding="utf-8")

    async def generate(self, brief: str, session_id: str) -> str:
        """
        Generate PRD from brief.
        Saves prd.md to session directory. Returns content string.
        """
        logger.info(f"[{session_id}] ProductAgent: generating PRD")

        content = await self.llm.complete(
            system=self._system,
            user=brief,
            max_tokens=_MAX_TOKENS,
            timeout=_TIMEOUT,
            session_id=session_id,
        )

        self.store.write(session_id, "prd.md", content)
        logger.info(f"[{session_id}] ProductAgent: prd.md written ({len(content)} chars)")
        return content
