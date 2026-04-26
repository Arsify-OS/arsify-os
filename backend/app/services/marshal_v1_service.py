"""
Marshal Engine v1 — Service wrapper for backend/app/services/

Adapts marshal_v1.py from 01-marshal-engine_zip into the target package:
  - Fixed all relative imports for backend/app/services/ location
  - run() returns None (background task, return value unused by Planner)
  - ProductAgent instantiated via LLMClient (matches existing product_agent.py interface)
  - SessionManager imported from session_manager (not session)
  - FileStore imported from local services (not storage.file_store)

Pipeline v1 steps:
  1. Validate brief (length)
  2. Generate PRD → ProductAgent
  3. Validate PRD structure → PrdValidator (fail fast on no Glossary)
  4. Extract EntityManifest → EntityExtractor (regex + LLM fallback)
  5. Build ContextBundle (PRD + EntityManifest)
  6. Generate SDD → ArchitectAgentV1 (with constraint_block)
  7. Generate API Spec → ArchitectAgentV1 (with constraint_block)
  8. Consistency check → ConsistencyEngineV1 (entity-name-aware)
  9. Decision: critical conflicts AND retries remaining?
     YES → rebuild ContextBundle with conflict list → back to step 6
     NO  → mark complete, deliver output

MAX_RETRIES = 2 (total Architect attempts = 3)
PRD_MAX_RETRIES = 1 (if PRD validation fails, regenerate once)
"""
import logging
from typing import Optional

from ..models.v1_schemas import EntityManifest, ContextBundle, PrdValidationResult
from ..models.schemas import (
    PipelineStatus,
    ConsistencyResult,
    Conflict,
)
from .file_store import FileStore
from .session_manager import SessionManager
from .llm_client import LLMClient
from .product_agent import ProductAgent
from .architect_agent_v1 import ArchitectAgentV1
from .consistency_engine_v1 import ConsistencyEngineV1
from .entity_extractor import EntityExtractor
from .prd_validator import PrdValidator

logger = logging.getLogger(__name__)

# Custom status values for v1 (stored in session.json custom_status field)
STATUS_VALIDATING_PRD = "validating_prd_structure"
STATUS_EXTRACTING_ENTITIES = "extracting_entity_manifest"


class MarshalV1:
    """
    Marshal Engine v1 — Consistency-Aware Decision Engine.

    This is the SSoT (Single Source of Truth) for all pipeline decisions.
    The Planner (main.py) holds one reference to this class and calls:
      - create_session(brief) → session_id
      - run(session_id, brief)  [as background task]

    All other components (ProductAgent, ArchitectAgentV1, ConsistencyEngineV1,
    EntityExtractor, PrdValidator) are owned and orchestrated by this class.
    The Planner never references these components directly.
    """

    MAX_RETRIES = 2
    PRD_MAX_RETRIES = 1

    def __init__(self, llm_gateway_url: str, storage_base: str = "/pipeline_outputs"):
        self.llm_gateway_url = llm_gateway_url

        # Storage layer
        self.file_store = FileStore(storage_base)
        self.session_manager = SessionManager(self.file_store)

        # LLM client (shared for ProductAgent)
        llm_client = LLMClient(llm_gateway_url)

        # All agents — owned by Marshal, not accessible from Planner
        self.product_agent = ProductAgent(llm_client, self.file_store)
        self.architect = ArchitectAgentV1(llm_gateway_url, self.file_store)
        self.consistency = ConsistencyEngineV1(llm_gateway_url)
        self.entity_extractor = EntityExtractor(llm_gateway_url)
        self.prd_validator = PrdValidator()

    def create_session(self, brief: str) -> str:
        """Create a new pipeline session. Returns session_id (UUID v4)."""
        return self.session_manager.create(brief)

    async def run(self, session_id: str, brief: str) -> None:
        """
        Execute the full v1 pipeline for a session.
        Called as a FastAPI BackgroundTask — return value is ignored.
        Exceptions are caught, stored in session, and re-raised.
        """
        try:
            await self._execute(session_id, brief)
        except Exception as e:
            logger.error(f"[{session_id}] MarshalV1 unhandled exception", exc_info=True)
            self.session_manager.fail(session_id, str(e))

    async def _execute(self, session_id: str, brief: str) -> None:

        # ── STEP 1: Generate PRD (with validation + retry) ──────────────────
        prd_content = await self._generate_and_validate_prd(session_id, brief)

        # ── STEP 2: Extract EntityManifest ───────────────────────────────────
        self.session_manager.update(
            session_id, PipelineStatus.GENERATING_PRD,
            step=2, custom_status=STATUS_EXTRACTING_ENTITIES
        )
        entity_manifest = await self.entity_extractor.extract(prd_content, session_id)

        if not entity_manifest.has_entities:
            logger.warning(
                f"[{session_id}] No entities extracted — "
                f"error: {entity_manifest.extraction_error}. "
                "Continuing without entity constraints."
            )
        else:
            logger.info(
                f"[{session_id}] EntityManifest: {entity_manifest.canonical_names}"
            )

        # ── STEP 3: Build ContextBundle ───────────────────────────────────────
        context = ContextBundle(
            prd_content=prd_content,
            entity_manifest=entity_manifest,
        )

        # ── STEP 4: Architect retry loop ──────────────────────────────────────
        consistency_result: Optional[ConsistencyResult] = None
        prior_conflicts: list[Conflict] = []

        for attempt in range(self.MAX_RETRIES + 1):
            logger.info(f"[{session_id}] Architect attempt {attempt}")

            # Generate SDD
            self.session_manager.update(
                session_id, PipelineStatus.GENERATING_SDD, step=3, attempt=attempt
            )
            sdd_content = await self.architect.generate_sdd(
                context=context,
                session_id=session_id,
                attempt=attempt,
                prior_conflicts=prior_conflicts,
            )
            # Update context snapshot with new SDD
            context = ContextBundle(
                prd_content=context.prd_content,
                entity_manifest=context.entity_manifest,
                sdd_content=sdd_content,
                api_content=context.api_content,
            )

            # Generate API Spec
            self.session_manager.update(
                session_id, PipelineStatus.GENERATING_API_SPEC, step=4, attempt=attempt
            )
            api_content = await self.architect.generate_api_spec(
                context=context,
                session_id=session_id,
                attempt=attempt,
            )
            context = ContextBundle(
                prd_content=context.prd_content,
                entity_manifest=context.entity_manifest,
                sdd_content=context.sdd_content,
                api_content=api_content,
            )

            # Consistency check (entity-aware)
            self.session_manager.update(
                session_id, PipelineStatus.VALIDATING_CONSISTENCY, step=5, attempt=attempt
            )
            consistency_result = await self.consistency.validate(
                session_id=session_id,
                context=context,
            )

            logger.info(
                f"[{session_id}] Consistency attempt {attempt}: "
                f"score={consistency_result.score}, "
                f"consistent={consistency_result.consistent}, "
                f"conflicts={len(consistency_result.conflicts)}"
            )

            # Decision gate
            critical = [c for c in consistency_result.conflicts if c.severity == "critical"]

            if not critical:
                logger.info(f"[{session_id}] No critical conflicts — accepting output")
                break

            if attempt < self.MAX_RETRIES:
                prior_conflicts = critical
                logger.warning(
                    f"[{session_id}] {len(critical)} critical conflict(s). "
                    f"Retrying Architect (attempt {attempt + 1}). "
                    f"Conflicts: {[c.description for c in critical]}"
                )
            else:
                logger.warning(
                    f"[{session_id}] Max retries reached. "
                    f"Delivering with score={consistency_result.score}."
                )

        # ── FINALIZE ──────────────────────────────────────────────────────────
        self.session_manager.update(
            session_id,
            PipelineStatus.COMPLETE,
            step=5,
            consistency_score=consistency_result.score if consistency_result else None,
            consistency_result=consistency_result.model_dump() if consistency_result else None,
        )

        logger.info(f"[{session_id}] MarshalV1 pipeline complete")

    async def _generate_and_validate_prd(self, session_id: str, brief: str) -> str:
        """
        Generate PRD and validate its structure.
        On validation failure: log warning and continue (pipeline does not abort).
        On catastrophic failure (no Glossary, no Features): regenerate once.
        """
        prd_content = ""
        for prd_attempt in range(self.PRD_MAX_RETRIES + 1):
            self.session_manager.update(
                session_id, PipelineStatus.GENERATING_PRD, step=1, attempt=prd_attempt
            )
            prd_content = await self.product_agent.generate(brief, session_id)

            # Validate structure
            self.session_manager.update(
                session_id, PipelineStatus.GENERATING_PRD,
                step=1, custom_status=STATUS_VALIDATING_PRD
            )
            validation = self.prd_validator.validate(prd_content, session_id)

            if validation.valid:
                return prd_content

            # Invalid — should we retry?
            if prd_attempt < self.PRD_MAX_RETRIES:
                logger.warning(
                    f"[{session_id}] PRD validation failed "
                    f"(missing: {validation.missing_sections}). Regenerating."
                )
                continue

            # Max PRD retries reached — continue with what we have
            logger.error(
                f"[{session_id}] PRD still invalid after {self.PRD_MAX_RETRIES + 1} attempts. "
                f"Missing: {validation.missing_sections}. Continuing anyway."
            )
            return prd_content

        return prd_content
