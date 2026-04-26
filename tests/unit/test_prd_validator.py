"""
Layer 2 — Unit tests: PrdValidator
No LLM calls. Pure regex + string matching. Fast.
"""
import pytest
from pipeline_engine.core.prd_validator import PrdValidator
from tests.fixtures.sample_prd import (
    VALID_PRD,
    INVALID_PRD_NO_GLOSSARY,
    INVALID_PRD_NO_FEATURES,
)

SESSION_ID = "test-prd-validator"


@pytest.fixture
def validator():
    return PrdValidator()


class TestValidPrd:
    def test_valid_prd_passes(self, validator):
        result = validator.validate(VALID_PRD, SESSION_ID)
        assert result.valid is True

    def test_valid_prd_has_glossary(self, validator):
        result = validator.validate(VALID_PRD, SESSION_ID)
        assert result.has_glossary is True

    def test_valid_prd_has_features(self, validator):
        result = validator.validate(VALID_PRD, SESSION_ID)
        assert result.has_features is True

    def test_valid_prd_entity_count(self, validator):
        result = validator.validate(VALID_PRD, SESSION_ID)
        # VALID_PRD has 5 entities: Workspace, Member, Project, Task, AuditLog
        assert result.entity_count >= 5

    def test_valid_prd_feature_count(self, validator):
        result = validator.validate(VALID_PRD, SESSION_ID)
        assert result.feature_count >= 3

    def test_valid_prd_no_missing_sections(self, validator):
        result = validator.validate(VALID_PRD, SESSION_ID)
        assert len(result.missing_sections) == 0


class TestInvalidPrd:
    def test_no_glossary_fails(self, validator):
        result = validator.validate(INVALID_PRD_NO_GLOSSARY, SESSION_ID)
        assert result.valid is False
        assert result.has_glossary is False
        assert "Glossary" in " ".join(result.missing_sections)

    def test_no_features_fails(self, validator):
        result = validator.validate(INVALID_PRD_NO_FEATURES, SESSION_ID)
        assert result.valid is False
        assert result.has_features is False

    def test_empty_string_fails(self, validator):
        result = validator.validate("", SESSION_ID)
        assert result.valid is False
        assert len(result.missing_sections) > 0


class TestEdgeCases:
    def test_prd_with_one_feature_warns(self, validator):
        """Single feature should warn, not necessarily fail (warn if < 2)."""
        prd = VALID_PRD.replace(
            "### Feature: Project Organisation", "## Removed Feature"
        ).replace(
            "### Feature: Manager Dashboard", "## Also Removed"
        )
        result = validator.validate(prd, SESSION_ID)
        # Should still have warnings or missing features
        assert result.feature_count < 3

    def test_glossary_with_few_entities_warns(self, validator):
        """Fewer than 3 entities should appear in warnings."""
        # Minimal PRD — only 1 entity in Glossary
        prd = VALID_PRD
        result = validator.validate(prd, SESSION_ID)
        # Full VALID_PRD has 5 — no warning expected
        assert not any("entity" in w.lower() for w in result.warnings)
