"""
Marshal — the pipeline orchestrator.

SDD responsibility:
  - Creates and updates sessions
  - Sequences ProductAgent → ArchitectAgent → ConsistencyEngine
  - Manages retry loop (max MAX_RETRIES + 1 total Architect attempts)
  - Marks session complete or failed

Does NOT:
  - Make LLM calls directly
  - Write document files directly
  - Contain prompt logic
"""

import logging
import os

from ..models.schemas import ConsistencyResult, PipelineStatus
from .architect_agent import ArchitectAgent
from .consistency_engine import ConsistencyEngine
from .file_store import FileStore
from .llm_client import LLMClient
from .product_agent import ProductAgent
from .session_manager import SessionManager

logger = logging.getLogger(__name__)

# SDD: MAX_RETRIES=2 → 3 total Architect attempts
_MAX_RETRIES = int(os.environ.get("PIPELINE_MAX_RETRIES", "2"))


class Marshal:
    """
    Owns the pipeline lifecycle.
    Instantiates all agents and runs them in sequence.
    """

    def __init__(self, llm_gateway_url: str, storage_base: str = "/pipeline_outputs"):
        file_store  = FileStore(storage_base)
        llm_client  = LLMClient(llm_gateway_url)

        self.file_store      = file_store
        self.session_manager = SessionManager(file_store)
        self.product_agent   = ProductAgent(llm_client, file_store)
        self.architect_agent = ArchitectAgent(llm_client, file_store)
        self.consistency_engine = ConsistencyEngine(llm_client)

    def create_session(self, brief: str) -> str:
        """Create a new pipeline session. Returns session_id."""
        return self.session_manager.create(brief)

    async def run(self, session_id: str, brief: str) -> None:
        """
        Execute the full pipeline for a session.
        Runs as a FastAPI BackgroundTask — exceptions are caught and stored.
        """
        logger.info(f"[{session_id}] Marshal: pipeline starting")
        try:
            await self._execute(session_id, brief)
        except Exception as exc:
            logger.error(f"[{session_id}] Marshal: unhandled exception", exc_info=True)
            self.session_manager.fail(session_id, str(exc))

    async def _execute(self, session_id: str, brief: str) -> None:

        # ── Step 1: Generate PRD ────────────────────────────────────────────
        self.session_manager.update(
            session_id, PipelineStatus.GENERATING_PRD, step=1
        )
        prd_content = await self.product_agent.generate(brief, session_id)

        # ── Steps 2–4: Architect + Consistency retry loop ───────────────────
        consistency_result: ConsistencyResult | None = None

        for attempt in range(_MAX_RETRIES + 1):
            logger.info(f"[{session_id}] Marshal: Architect attempt {attempt}")

            # Step 2: Generate SDD
            self.session_manager.update(
                session_id, PipelineStatus.GENERATING_SDD,
                step=2, attempt=attempt,
            )
            sdd_content = await self.architect_agent.generate_sdd(
                prd_content=prd_content,
                session_id=session_id,
                attempt=attempt,
                previous_conflicts=(
                    consistency_result.conflicts if consistency_result else []
                ),
            )

            # Step 3: Generate API Spec
            self.session_manager.update(
                session_id, PipelineStatus.GENERATING_API_SPEC,
                step=3, attempt=attempt,
            )
            api_content = await self.architect_agent.generate_api_spec(
                prd_content=prd_content,
                sdd_content=sdd_content,
                session_id=session_id,
                attempt=attempt,
            )

            # Step 4: Validate consistency
            self.session_manager.update(
                session_id, PipelineStatus.VALIDATING_CONSISTENCY,
                step=4, attempt=attempt,
            )
            consistency_result = await self.consistency_engine.validate(
                session_id=session_id,
                prd_content=prd_content,
                sdd_content=sdd_content,
                api_content=api_content,
            )

            # Decide: accept or retry
            critical_conflicts = [
                c for c in consistency_result.conflicts
                if c.severity.value == "critical"
            ]

            if not critical_conflicts:
                logger.info(
                    f"[{session_id}] Marshal: consistency passed "
                    f"(score={consistency_result.score}, attempt={attempt})"
                )
                break

            if attempt < _MAX_RETRIES:
                logger.warning(
                    f"[{session_id}] Marshal: {len(critical_conflicts)} critical conflict(s), "
                    f"retrying Architect (attempt {attempt + 1})"
                )
            else:
                logger.warning(
                    f"[{session_id}] Marshal: max retries reached. "
                    f"Delivering with consistency score {consistency_result.score}."
                )

        # ── Finalize ────────────────────────────────────────────────────────
        self.session_manager.update(
            session_id,
            PipelineStatus.COMPLETE,
            step=4,
            consistency_score=consistency_result.score if consistency_result else None,
            consistency_result=(
                consistency_result.model_dump() if consistency_result else None
            ),
        )
        logger.info(f"[{session_id}] Marshal: pipeline complete")
