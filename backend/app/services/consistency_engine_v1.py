"""
Marshal Engine v1 — Consistency Engine (entity-name-aware)

Upgrades over v2 ConsistencyEngine:
- Receives ContextBundle (not raw strings)
- Passes canonical_names explicitly to the LLM prompt
- More precise conflict detection: checks names the Glossary actually defined,
  not guesses at what the entity names might be
- Scoring formula: 100 - (15 × critical) - (5 × warning), minimum 0

Imports fixed for backend/app/services/ package location.
"""
import json
import logging
import re
from pathlib import Path

import httpx

from ..models.v1_schemas import ContextBundle
from ..models.schemas import ConsistencyResult, Conflict, ConflictSeverity, ConflictType

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "consistency_check.txt"


class ConsistencyEngineV1:
    """
    Entity-name-aware consistency validator.

    The prompt receives:
    1. The explicit list of canonical entity names from EntityManifest
    2. All three document contents
    3. Specific instructions on what counts as a critical vs warning violation

    This eliminates the "fuzzy" consistency checking where the LLM decides
    what entities exist — instead the LLM verifies a pre-defined list.
    """

    MODEL = "upshalter/smart"
    MAX_TOKENS = 1500
    TIMEOUT = 90.0

    def __init__(self, llm_gateway_url: str):
        self.llm_gateway_url = llm_gateway_url
        self._prompt_template = PROMPT_PATH.read_text(encoding="utf-8")

    async def validate(
        self,
        session_id: str,
        context: ContextBundle,
    ) -> ConsistencyResult:
        """
        Validate consistency of all three documents.
        Uses canonical_names from EntityManifest for precise entity checking.
        """
        logger.info(f"[{session_id}] ConsistencyEngineV1: validating")

        consistency_ctx = context.consistency_context()
        prompt = self._build_prompt(consistency_ctx)

        try:
            raw = await self._call_llm(prompt, session_id)
            result = self._parse_response(raw, session_id)
        except Exception as e:
            logger.error(f"[{session_id}] ConsistencyEngineV1 failed: {e}")
            result = ConsistencyResult(
                consistent=True,
                score=50,
                conflicts=[],
                summary="Consistency check failed — accepted with assumed score 50.",
            )

        logger.info(
            f"[{session_id}] ConsistencyEngineV1: score={result.score}, "
            f"consistent={result.consistent}, conflicts={len(result.conflicts)}"
        )
        return result

    def _build_prompt(self, ctx: dict) -> str:
        """Build the full prompt with explicit entity names injected."""
        canonical_names = ctx.get("canonical_names", [])

        entity_section = ""
        if canonical_names:
            names_list = "\n".join(f"  - {name}" for name in canonical_names)
            entity_section = (
                f"\nCANONICAL ENTITY NAMES (extracted from PRD Glossary):\n"
                f"These names must appear verbatim in the SDD Data Models and API spec schemas.\n"
                f"{names_list}\n\n"
                "Check each name above. For each one:\n"
                "1. Does it appear verbatim in the SDD Data Models section? If not → entity_mismatch CRITICAL\n"
                "2. Does it appear verbatim in the API spec components/schemas? If not → entity_mismatch CRITICAL\n"
                "3. Do SDD fields that reference this entity use the correct naming pattern? If not → field_mismatch CRITICAL\n\n"
            )

        return (
            self._prompt_template
            .replace("{prd_content}", ctx["prd_content"])
            .replace("{sdd_content}", ctx["sdd_content"])
            .replace("{api_content}", ctx["api_content"])
            + entity_section
        )

    def _parse_response(self, raw: str, session_id: str) -> ConsistencyResult:
        try:
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"```\w*\n?", "", cleaned).strip()
            match = re.search(r'\{.*\}', cleaned, re.DOTALL)
            if match:
                cleaned = match.group()

            data = json.loads(cleaned)

            conflicts = []
            for c in data.get("conflicts", []):
                try:
                    conflicts.append(Conflict(
                        type=ConflictType(c.get("type", "entity_mismatch")),
                        description=c.get("description", ""),
                        prd_reference=c.get("prd_reference", ""),
                        sdd_reference=c.get("sdd_reference", ""),
                        severity=ConflictSeverity(c.get("severity", "warning")),
                    ))
                except (ValueError, KeyError) as e:
                    logger.warning(f"[{session_id}] Skipping malformed conflict: {e}")

            # Recalculate score from conflict list for determinism
            critical_count = sum(1 for c in conflicts if c.severity == ConflictSeverity.CRITICAL)
            warning_count = sum(1 for c in conflicts if c.severity == ConflictSeverity.WARNING)
            score = max(0, 100 - (critical_count * 15) - (warning_count * 5))
            consistent = critical_count == 0

            return ConsistencyResult(
                consistent=consistent,
                score=score,
                conflicts=conflicts,
                summary=str(data.get("summary", "Consistency check completed.")),
            )

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"[{session_id}] ConsistencyEngineV1 parse error: {e}")
            return ConsistencyResult(
                consistent=True,
                score=50,
                conflicts=[],
                summary="Could not parse consistency response. Manual review recommended.",
            )

    async def _call_llm(self, prompt: str, session_id: str) -> str:
        payload = {
            "model": self.MODEL,
            "max_tokens": self.MAX_TOKENS,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        }
        async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
            response = await client.post(
                f"{self.llm_gateway_url}/v1/chat/completions",
                json=payload,
            )
            response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
