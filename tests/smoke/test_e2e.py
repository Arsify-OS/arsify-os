"""
Layer 4 — End-to-end smoke tests
REAL LLM calls via or_gateway. Real cost. Run before every deploy.

Requirements:
  - PIPELINE_LLM_GATEWAY set to a running or_gateway
  - OPENROUTER_API_KEY set in environment

Run selectively:
  pytest tests/smoke/ -v -m smoke
  pytest tests/smoke/ -v -m smoke -k "saas"  (single brief)

Skipped automatically if PIPELINE_LLM_GATEWAY is not set.
"""
import os
import time
import tempfile
import pytest

from pipeline_engine.core.marshal_v1 import MarshalV1
from pipeline_engine.models.schemas import PipelineStatus
from tests.fixtures.briefs import BRIEF_SAAS, BRIEF_MARKETPLACE, BRIEF_API_PRODUCT

GATEWAY = os.environ.get("PIPELINE_LLM_GATEWAY", "")
SMOKE_SKIP = not GATEWAY
SKIP_REASON = "Set PIPELINE_LLM_GATEWAY to run smoke tests"

pytestmark = pytest.mark.smoke


@pytest.fixture(scope="module")
def tmpdir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture(scope="module")
def marshal(tmpdir):
    if SMOKE_SKIP:
        pytest.skip(SKIP_REASON)
    return MarshalV1(llm_gateway_url=GATEWAY, storage_base=tmpdir)


# ── Success criteria thresholds ───────────────────────────────────────────

MIN_CONSISTENCY_SCORE = 70     # Any score below this = system failure
MAX_RUNTIME_SECONDS = 180      # From run() start to completion
MIN_DOC_LENGTH_CHARS = 500     # Each document must be substantive


# ── Canonical brief smoke tests ───────────────────────────────────────────

class TestSaasBrief:
    """Brief A: Project management SaaS — 5+ entities expected"""

    @pytest.mark.asyncio
    async def test_saas_pipeline_completes(self, marshal):
        session_id = marshal.create_session(BRIEF_SAAS)
        t0 = time.monotonic()
        result = await marshal.run(session_id, BRIEF_SAAS)
        elapsed = time.monotonic() - t0

        assert result.status == PipelineStatus.COMPLETE, (
            f"Pipeline failed. Error in session.json."
        )
        assert elapsed < MAX_RUNTIME_SECONDS, (
            f"Pipeline took {elapsed:.1f}s — exceeds {MAX_RUNTIME_SECONDS}s limit"
        )

    @pytest.mark.asyncio
    async def test_saas_consistency_score(self, marshal):
        session_id = marshal.create_session(BRIEF_SAAS)
        result = await marshal.run(session_id, BRIEF_SAAS)

        assert result.consistency_score is not None
        assert result.consistency_score >= MIN_CONSISTENCY_SCORE, (
            f"Score {result.consistency_score} below threshold {MIN_CONSISTENCY_SCORE}. "
            f"Conflicts: {[c.description for c in (result.consistency_result.conflicts or [])]}"
        )

    @pytest.mark.asyncio
    async def test_saas_documents_are_substantive(self, marshal):
        session_id = marshal.create_session(BRIEF_SAAS)
        result = await marshal.run(session_id, BRIEF_SAAS)

        for doc_name, content in result.outputs.items():
            assert len(content) >= MIN_DOC_LENGTH_CHARS, (
                f"{doc_name} is too short ({len(content)} chars). "
                f"Minimum: {MIN_DOC_LENGTH_CHARS} chars."
            )

    @pytest.mark.asyncio
    async def test_saas_prd_contains_glossary(self, marshal):
        session_id = marshal.create_session(BRIEF_SAAS)
        result = await marshal.run(session_id, BRIEF_SAAS)
        assert "Glossary" in result.outputs["prd"], "PRD missing Glossary section"

    @pytest.mark.asyncio
    async def test_saas_api_spec_is_valid_yaml(self, marshal):
        import yaml
        session_id = marshal.create_session(BRIEF_SAAS)
        result = await marshal.run(session_id, BRIEF_SAAS)
        # Should parse without exception
        parsed = yaml.safe_load(result.outputs["api_spec"])
        assert "openapi" in parsed, "API spec missing 'openapi' key"
        assert "paths" in parsed, "API spec missing 'paths' key"
        assert "components" in parsed, "API spec missing 'components' key"


class TestMarketplaceBrief:
    """Brief B: Peer-to-peer marketplace"""

    @pytest.mark.asyncio
    async def test_marketplace_pipeline_completes(self, marshal):
        session_id = marshal.create_session(BRIEF_MARKETPLACE)
        result = await marshal.run(session_id, BRIEF_MARKETPLACE)
        assert result.status == PipelineStatus.COMPLETE

    @pytest.mark.asyncio
    async def test_marketplace_score_above_threshold(self, marshal):
        session_id = marshal.create_session(BRIEF_MARKETPLACE)
        result = await marshal.run(session_id, BRIEF_MARKETPLACE)
        assert result.consistency_score >= MIN_CONSISTENCY_SCORE, (
            f"Marketplace brief: score {result.consistency_score} below {MIN_CONSISTENCY_SCORE}"
        )


class TestApiProductBrief:
    """Brief C: Document parsing API product"""

    @pytest.mark.asyncio
    async def test_api_product_pipeline_completes(self, marshal):
        session_id = marshal.create_session(BRIEF_API_PRODUCT)
        result = await marshal.run(session_id, BRIEF_API_PRODUCT)
        assert result.status == PipelineStatus.COMPLETE

    @pytest.mark.asyncio
    async def test_api_product_score_above_threshold(self, marshal):
        session_id = marshal.create_session(BRIEF_API_PRODUCT)
        result = await marshal.run(session_id, BRIEF_API_PRODUCT)
        assert result.consistency_score >= MIN_CONSISTENCY_SCORE

    @pytest.mark.asyncio
    async def test_api_product_spec_has_components(self, marshal):
        import yaml
        session_id = marshal.create_session(BRIEF_API_PRODUCT)
        result = await marshal.run(session_id, BRIEF_API_PRODUCT)
        parsed = yaml.safe_load(result.outputs["api_spec"])
        schemas = parsed.get("components", {}).get("schemas", {})
        assert len(schemas) >= 3, (
            f"Expected ≥3 schemas in API spec, got {len(schemas)}: {list(schemas.keys())}"
        )


# ── Aggregate smoke report ────────────────────────────────────────────────

class TestSmokeReport:
    """Runs all three briefs and reports aggregate results."""

    @pytest.mark.asyncio
    async def test_three_brief_aggregate(self, marshal):
        """
        The single most important smoke test.
        All three canonical briefs must complete with score ≥ MIN_CONSISTENCY_SCORE.
        This maps directly to Phase 1.5 Strategic Lock success criterion:
        'Passes 3 real-world briefs: SaaS, marketplace, API product.'
        """
        briefs = {
            "saas": BRIEF_SAAS,
            "marketplace": BRIEF_MARKETPLACE,
            "api_product": BRIEF_API_PRODUCT,
        }
        results = {}

        for name, brief in briefs.items():
            session_id = marshal.create_session(brief)
            result = await marshal.run(session_id, brief)
            results[name] = {
                "status": result.status,
                "score": result.consistency_score,
                "conflicts": len(result.consistency_result.conflicts) if result.consistency_result else 0,
            }

        failures = []
        for name, r in results.items():
            if r["status"] != PipelineStatus.COMPLETE:
                failures.append(f"{name}: pipeline failed")
            elif r["score"] < MIN_CONSISTENCY_SCORE:
                failures.append(
                    f"{name}: score {r['score']} below {MIN_CONSISTENCY_SCORE} "
                    f"({r['conflicts']} conflict(s))"
                )

        # Print summary regardless
        print("\n── Smoke Test Summary ──")
        for name, r in results.items():
            status_sym = "✓" if r["score"] >= MIN_CONSISTENCY_SCORE else "✗"
            print(f"  {status_sym} {name}: score={r['score']}, conflicts={r['conflicts']}")

        assert not failures, "Smoke test failures:\n" + "\n".join(failures)
