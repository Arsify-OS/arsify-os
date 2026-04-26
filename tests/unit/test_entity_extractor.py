"""
Layer 2 — Unit tests: EntityExtractor (regex path only)
The LLM fallback path is tested in integration tests with mocked LLM.
"""
import pytest
from pipeline_engine.core.entity_extractor import EntityExtractor
from tests.fixtures.sample_prd import VALID_PRD, INVALID_PRD_NO_GLOSSARY, CANONICAL_ENTITIES

SESSION_ID = "test-entity-extractor"

# Use a dummy gateway URL — regex path makes no HTTP calls
GATEWAY = "http://localhost:9999"


@pytest.fixture
def extractor():
    return EntityExtractor(llm_gateway_url=GATEWAY)


class TestRegexExtraction:
    @pytest.mark.asyncio
    async def test_extracts_all_canonical_names(self, extractor):
        manifest = await extractor.extract(VALID_PRD, SESSION_ID)
        for name in CANONICAL_ENTITIES:
            assert name in manifest.canonical_names, (
                f"Expected '{name}' in canonical_names, got: {manifest.canonical_names}"
            )

    @pytest.mark.asyncio
    async def test_extracts_definitions(self, extractor):
        manifest = await extractor.extract(VALID_PRD, SESSION_ID)
        assert "Member" in manifest.definitions
        assert len(manifest.definitions["Member"]) > 10

    @pytest.mark.asyncio
    async def test_extracts_feature_names(self, extractor):
        manifest = await extractor.extract(VALID_PRD, SESSION_ID)
        assert "Task Management" in manifest.features
        assert "Workspace Management" in manifest.features

    @pytest.mark.asyncio
    async def test_has_entities_true_on_success(self, extractor):
        manifest = await extractor.extract(VALID_PRD, SESSION_ID)
        assert manifest.has_entities is True

    @pytest.mark.asyncio
    async def test_empty_string_returns_empty_manifest(self, extractor):
        manifest = await extractor.extract("", SESSION_ID)
        # No entities in empty string — should not crash
        assert isinstance(manifest.canonical_names, (list, tuple))

    @pytest.mark.asyncio
    async def test_no_glossary_returns_empty_not_error(self, extractor):
        manifest = await extractor.extract(INVALID_PRD_NO_GLOSSARY, SESSION_ID)
        # Should return manifest (possibly empty), not raise
        assert hasattr(manifest, "canonical_names")
        assert hasattr(manifest, "has_entities")


class TestConstraintBlock:
    @pytest.mark.asyncio
    async def test_constraint_block_contains_entity_names(self, extractor):
        manifest = await extractor.extract(VALID_PRD, SESSION_ID)
        block = manifest.constraint_block()
        for name in manifest.canonical_names:
            assert name in block, f"'{name}' not found in constraint_block"

    @pytest.mark.asyncio
    async def test_constraint_block_contains_field_naming_rule(self, extractor):
        manifest = await extractor.extract(VALID_PRD, SESSION_ID)
        block = manifest.constraint_block()
        # Should contain at least one "_id" field naming example
        assert "_id" in block

    @pytest.mark.asyncio
    async def test_empty_manifest_constraint_block_safe(self, extractor):
        manifest = await extractor.extract("", SESSION_ID)
        # Even empty manifest should return a safe string
        block = manifest.constraint_block()
        assert isinstance(block, str)
        assert len(block) > 0
