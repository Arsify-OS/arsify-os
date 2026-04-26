"""
Layer 3 — Integration tests: MarshalV1 full pipeline
Uses mock LLM. Tests the real pipeline code, real session state, real file I/O.
"""
import os
import json
import pytest
import tempfile

from pipeline_engine.core.marshal_v1 import MarshalV1
from pipeline_engine.models.schemas import PipelineStatus
from tests.integration.mock_llm import (
    patch_llm,
    VALID_PRD,
    VALID_SDD,
    VALID_API_SPEC,
    PERFECT_CONSISTENCY_RESULT,
    ONE_CRITICAL_CONSISTENCY_RESULT,
    BROKEN_SDD_WRONG_ENTITY,
    ResponseSequence,
)
from tests.fixtures.briefs import BRIEF_MINIMAL

GATEWAY = "http://mock-gateway:4000"


@pytest.fixture
def tmpdir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def marshal(tmpdir):
    return MarshalV1(llm_gateway_url=GATEWAY, storage_base=tmpdir)


# ── Happy path ─────────────────────────────────────────────────────────────

class TestHappyPath:
    @pytest.mark.asyncio
    async def test_pipeline_runs_to_complete(self, marshal, tmpdir):
        with patch_llm():
            session_id = marshal.create_session(BRIEF_MINIMAL)
            result = await marshal.run(session_id, BRIEF_MINIMAL)

        assert result.status == PipelineStatus.COMPLETE

    @pytest.mark.asyncio
    async def test_session_json_written(self, marshal, tmpdir):
        with patch_llm():
            session_id = marshal.create_session(BRIEF_MINIMAL)
            await marshal.run(session_id, BRIEF_MINIMAL)

        session_path = os.path.join(tmpdir, session_id, "session.json")
        assert os.path.exists(session_path)
        data = json.loads(open(session_path).read())
        assert data["status"] == "complete"

    @pytest.mark.asyncio
    async def test_all_three_output_files_written(self, marshal, tmpdir):
        with patch_llm():
            session_id = marshal.create_session(BRIEF_MINIMAL)
            await marshal.run(session_id, BRIEF_MINIMAL)

        session_dir = os.path.join(tmpdir, session_id)
        assert os.path.exists(os.path.join(session_dir, "prd.md"))
        assert os.path.exists(os.path.join(session_dir, "sdd.md"))
        assert os.path.exists(os.path.join(session_dir, "api_spec.yaml"))

    @pytest.mark.asyncio
    async def test_consistency_score_in_result(self, marshal, tmpdir):
        with patch_llm(consistency=PERFECT_CONSISTENCY_RESULT):
            session_id = marshal.create_session(BRIEF_MINIMAL)
            result = await marshal.run(session_id, BRIEF_MINIMAL)

        assert result.consistency_score == 100

    @pytest.mark.asyncio
    async def test_output_bundle_contains_content(self, marshal, tmpdir):
        with patch_llm():
            session_id = marshal.create_session(BRIEF_MINIMAL)
            result = await marshal.run(session_id, BRIEF_MINIMAL)

        assert len(result.outputs["prd"]) > 100
        assert len(result.outputs["sdd"]) > 100
        assert len(result.outputs["api_spec"]) > 100


# ── Session state machine ─────────────────────────────────────────────────

class TestSessionStateMachine:
    @pytest.mark.asyncio
    async def test_session_starts_as_queued(self, marshal, tmpdir):
        session_id = marshal.create_session(BRIEF_MINIMAL)
        state = marshal.session_manager.get(session_id)
        assert state.status == PipelineStatus.QUEUED

    @pytest.mark.asyncio
    async def test_session_ends_as_complete(self, marshal, tmpdir):
        with patch_llm():
            session_id = marshal.create_session(BRIEF_MINIMAL)
            await marshal.run(session_id, BRIEF_MINIMAL)

        state = marshal.session_manager.get(session_id)
        assert state.status == PipelineStatus.COMPLETE

    @pytest.mark.asyncio
    async def test_session_has_timestamps(self, marshal, tmpdir):
        with patch_llm():
            session_id = marshal.create_session(BRIEF_MINIMAL)
            await marshal.run(session_id, BRIEF_MINIMAL)

        state = marshal.session_manager.get(session_id)
        assert state.created_at is not None
        assert state.completed_at is not None

    @pytest.mark.asyncio
    async def test_session_not_found_returns_none(self, marshal, tmpdir):
        state = marshal.session_manager.get("nonexistent-session-id")
        assert state is None


# ── Retry loop ────────────────────────────────────────────────────────────

class TestRetryLoop:
    @pytest.mark.asyncio
    async def test_retry_on_critical_conflict(self, marshal, tmpdir):
        """
        First consistency check → critical conflict → retry.
        Second consistency check → clean → complete.
        """
        import json

        seq = [
            VALID_PRD,                          # ProductAgent PRD
            BROKEN_SDD_WRONG_ENTITY,            # ArchitectAgent SDD (bad)
            VALID_API_SPEC,                     # ArchitectAgent API
            ONE_CRITICAL_CONSISTENCY_RESULT,    # ConsistencyEngine → fail
            VALID_SDD,                          # ArchitectAgent SDD retry (good)
            VALID_API_SPEC,                     # ArchitectAgent API retry
            PERFECT_CONSISTENCY_RESULT,         # ConsistencyEngine → pass
        ]
        with patch_llm(custom_sequence=seq):
            session_id = marshal.create_session(BRIEF_MINIMAL)
            result = await marshal.run(session_id, BRIEF_MINIMAL)

        assert result.status == PipelineStatus.COMPLETE
        # After retry, should pass
        assert result.consistency_score == 100

    @pytest.mark.asyncio
    async def test_max_retries_delivers_with_warnings(self, marshal, tmpdir):
        """
        All consistency checks → critical conflicts → max retries → deliver anyway.
        """
        seq = (
            [VALID_PRD]                           # PRD
            + [BROKEN_SDD_WRONG_ENTITY, VALID_API_SPEC, ONE_CRITICAL_CONSISTENCY_RESULT] * 3
            # 3 Architect attempts, all fail → deliver
        )
        with patch_llm(custom_sequence=seq):
            session_id = marshal.create_session(BRIEF_MINIMAL)
            result = await marshal.run(session_id, BRIEF_MINIMAL)

        # Pipeline completes even with persistent conflicts
        assert result.status == PipelineStatus.COMPLETE
        # Score will be < 100 due to unresolved conflicts
        assert result.consistency_score < 100

    @pytest.mark.asyncio
    async def test_attempt_count_in_session(self, marshal, tmpdir):
        """Session.json should record the final attempt number."""
        with patch_llm():
            session_id = marshal.create_session(BRIEF_MINIMAL)
            await marshal.run(session_id, BRIEF_MINIMAL)

        state = marshal.session_manager.get(session_id)
        # Attempt 0 on first clean pass
        assert state.attempt == 0


# ── Brief validation ──────────────────────────────────────────────────────

class TestBriefValidation:
    @pytest.mark.asyncio
    async def test_short_brief_raises(self, marshal, tmpdir):
        from pydantic import ValidationError
        from pipeline_engine.models.schemas import PipelineRequest

        with pytest.raises(ValidationError):
            PipelineRequest(brief="too short")

    @pytest.mark.asyncio
    async def test_valid_brief_accepted(self, marshal, tmpdir):
        from pipeline_engine.models.schemas import PipelineRequest

        req = PipelineRequest(brief=BRIEF_MINIMAL)
        assert len(req.brief) >= 50
