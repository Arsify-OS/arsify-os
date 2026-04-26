"""
ConsistencyEngine — validates cross-document consistency.

SDD responsibility: reads PRD + SDD + API spec, returns ConsistencyResult.
Uses JSON-mode LLM call. Falls back to conservative result on parse failure.
max_tokens: 1500 (SDD table: 1000 for consistency — using 1500 for safety).
"""

import json
import logging
import re
from pathlib import Path

from ..models.schemas import (
    Conflict,
    ConflictSeverity,
    ConflictType,
    ConsistencyResult,
)
from .llm_client import LLMClient

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "consistency_check.txt"

_MAX_TOKENS = 1500
_TIMEOUT    = 90.0


class ConsistencyEngine:
    """
    Validates PRD/SDD/API spec alignment.
    Returns ConsistencyResult with score 0–100 and conflict list.
    """

    def __init__(self, llm_client: LLMClient):
        self.llm              = llm_client
        self._prompt_template = _PROMPT_PATH.read_text(encoding="utf-8")

    async def validate(
        self,
        session_id:  str,
        prd_content: str,
        sdd_content: str,
        api_content: str,
    ) -> ConsistencyResult:
        """
        Validate consistency across all three documents.
        Returns ConsistencyResult. On LLM failure returns conservative result (score=0).
        """
        logger.info(f"[{session_id}] ConsistencyEngine: validating")

        prompt = (
            self._prompt_template
            .replace("{prd_content}", prd_content)
            .replace("{sdd_content}", sdd_content)
            .replace("{api_content}", api_content)
        )

        try:
            raw = await self.llm.complete(
                system=prompt,
                user="Produce the consistency report as valid JSON.",
                max_tokens=_MAX_TOKENS,
                timeout=_TIMEOUT,
                session_id=session_id,
                response_format={"type": "json_object"},
            )
            result = self._parse_response(raw, session_id)
        except Exception as exc:
            logger.error(
                f"[{session_id}] ConsistencyEngine: LLM call failed, "
                f"returning conservative result. Error: {exc}"
            )
            result = self._conservative_result()

        logger.info(
            f"[{session_id}] ConsistencyEngine: "
            f"score={result.score}, consistent={result.consistent}, "
            f"conflicts={len(result.conflicts)}"
        )
        return result

    # ── Parsing ───────────────────────────────────────────────────────────────

    def _parse_response(self, raw: str, session_id: str) -> ConsistencyResult:
        """Parse JSON response from LLM into ConsistencyResult."""
        try:
            # Strip markdown fences if the model added them despite instructions
            cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            logger.warning(
                f"[{session_id}] ConsistencyEngine: JSON parse failed: {exc}. "
                "Returning conservative result."
            )
            return self._conservative_result()

        try:
            conflicts = []
            for raw_c in data.get("conflicts", []):
                try:
                    conflicts.append(
                        Conflict(
                            type=ConflictType(raw_c.get("type", "entity_mismatch")),
                            description=raw_c.get("description", ""),
                            prd_reference=raw_c.get("prd_reference", ""),
                            sdd_reference=raw_c.get("sdd_reference", ""),
                            severity=ConflictSeverity(raw_c.get("severity", "warning")),
                        )
                    )
                except (ValueError, KeyError) as exc:
                    logger.warning(f"[{session_id}] Skipping malformed conflict: {exc}")

            score     = int(data.get("score", 0))
            score     = max(0, min(100, score))
            consistent = bool(data.get("consistent", False))
            summary   = str(data.get("summary", "Consistency validation completed."))

            return ConsistencyResult(
                consistent=consistent,
                score=score,
                conflicts=conflicts,
                summary=summary,
            )

        except Exception as exc:
            logger.warning(
                f"[{session_id}] ConsistencyEngine: result construction failed: {exc}. "
                "Returning conservative result."
            )
            return self._conservative_result()

    def _conservative_result(self) -> ConsistencyResult:
        """Returned when LLM call or parse fails. Triggers retry in Marshal."""
        return ConsistencyResult(
            consistent=False,
            score=0,
            conflicts=[
                Conflict(
                    type=ConflictType.ENTITY_MISMATCH,
                    description="Consistency validation could not be completed due to a system error.",
                    prd_reference="N/A",
                    sdd_reference="N/A",
                    severity=ConflictSeverity.CRITICAL,
                )
            ],
            summary="Consistency engine failed. Conservative result returned.",
        )
