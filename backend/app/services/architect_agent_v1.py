"""
Marshal Engine v1 — Architect Agent (entity-manifest-aware)

Upgrades over v2 ArchitectAgent:
- Accepts ContextBundle instead of raw prd_content string
- Injects EntityManifest.constraint_block() at the TOP of every prompt
- On retry: receives prior critical conflicts with targeted correction instructions
- Uses ContextBundle.architect_sdd_context() and .architect_api_context() for assembly

Imports fixed for backend/app/services/ package location.
"""
import logging
from pathlib import Path
from typing import Optional

import httpx

from ..models.v1_schemas import ContextBundle
from ..models.schemas import Conflict
from .file_store import FileStore

logger = logging.getLogger(__name__)

SDD_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "architect_sdd.txt"
API_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "architect_api.txt"


class ArchitectAgentV1:
    """
    Generates SDD and API Spec from ContextBundle.

    The key difference from v2: the EntityManifest constraint_block is
    injected at the TOP of every system prompt, before the task instructions.
    This means the model sees the entity constraints BEFORE it sees the
    structural template it needs to fill — making constraint adherence
    the primary frame, not an afterthought.

    Prompt assembly order (SDD call):
      1. constraint_block (entity names — HARD CONSTRAINTS)
      2. [optional] conflict corrections (on retry)
      3. PRD content (source of truth)
      4. SDD generation instructions (structural template)

    Prompt assembly order (API call):
      1. constraint_block (entity names)
      2. PRD content
      3. SDD content (use these exact schemas)
      4. API spec generation instructions
    """

    MODEL = "upshalter/smart"
    MAX_TOKENS_SDD = 4000
    MAX_TOKENS_API = 3500
    TIMEOUT = 120.0

    def __init__(self, llm_gateway_url: str, file_store: FileStore):
        self.llm_gateway_url = llm_gateway_url
        self.store = file_store
        self._sdd_instructions = SDD_PROMPT_PATH.read_text(encoding="utf-8")
        self._api_instructions = API_PROMPT_PATH.read_text(encoding="utf-8")

    async def generate_sdd(
        self,
        context: ContextBundle,
        session_id: str,
        attempt: int = 0,
        prior_conflicts: Optional[list] = None,
    ) -> str:
        """
        Generate SDD with entity constraints injected.
        On retry: context includes prior conflicts for targeted correction.
        """
        logger.info(f"[{session_id}] ArchitectAgentV1: generating SDD (attempt {attempt})")

        user_message = context.architect_sdd_context(prior_conflicts=prior_conflicts)

        content = await self._call_llm(
            system=self._sdd_instructions,
            user_message=user_message,
            max_tokens=self.MAX_TOKENS_SDD,
            session_id=session_id,
        )

        self.store.write(session_id, "sdd.md", content)
        logger.info(f"[{session_id}] ArchitectAgentV1: SDD written ({len(content)} chars)")
        return content

    async def generate_api_spec(
        self,
        context: ContextBundle,
        session_id: str,
        attempt: int = 0,
    ) -> str:
        """
        Generate API Spec with entity constraints + PRD + SDD in context.
        """
        logger.info(f"[{session_id}] ArchitectAgentV1: generating API spec (attempt {attempt})")

        user_message = context.architect_api_context()

        content = await self._call_llm(
            system=self._api_instructions,
            user_message=user_message,
            max_tokens=self.MAX_TOKENS_API,
            session_id=session_id,
        )

        content = self._strip_yaml_fences(content)
        self.store.write(session_id, "api_spec.yaml", content)
        logger.info(f"[{session_id}] ArchitectAgentV1: API spec written ({len(content)} chars)")
        return content

    @staticmethod
    def _strip_yaml_fences(content: str) -> str:
        content = content.strip()
        if content.startswith("```yaml"):
            content = content[7:]
        elif content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        return content.strip()

    async def _call_llm(self, system: str, user_message: str, max_tokens: int, session_id: str) -> str:
        payload = {
            "model": self.MODEL,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_message},
            ],
        }
        async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
            try:
                response = await client.post(
                    f"{self.llm_gateway_url}/v1/chat/completions",
                    json=payload,
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                logger.error(f"[{session_id}] ArchitectAgentV1 HTTP {e.response.status_code}")
                raise

        content = response.json()["choices"][0]["message"]["content"]
        if not content or len(content.strip()) < 100:
            raise ValueError(f"[{session_id}] ArchitectAgentV1: suspiciously short response")
        return content.strip()
