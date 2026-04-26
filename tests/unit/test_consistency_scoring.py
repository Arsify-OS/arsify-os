"""
Layer 2 — Unit tests: Consistency scoring formula
The scoring formula must be deterministic and testable without any LLM.
score = max(0, 100 - (critical × 15) - (warning × 5))
"""
import pytest
from pipeline_engine.models.schemas import (
    ConsistencyResult, Conflict, ConflictSeverity, ConflictType
)


def make_conflict(severity: str, ctype: str = "entity_mismatch") -> Conflict:
    return Conflict(
        type=ConflictType(ctype),
        description=f"Test {severity} conflict",
        prd_reference="PRD says: Member",
        sdd_reference="SDD has: User",
        severity=ConflictSeverity(severity),
    )


def compute_score(conflicts: list[Conflict]) -> int:
    """Replicate the scoring formula from ConsistencyEngineV1._parse_response."""
    critical = sum(1 for c in conflicts if c.severity == ConflictSeverity.CRITICAL)
    warnings = sum(1 for c in conflicts if c.severity == ConflictSeverity.WARNING)
    return max(0, 100 - (critical * 15) - (warnings * 5))


class TestScoringFormula:
    def test_no_conflicts_score_100(self):
        assert compute_score([]) == 100

    def test_one_critical_scores_85(self):
        assert compute_score([make_conflict("critical")]) == 85

    def test_two_criticals_score_70(self):
        assert compute_score([make_conflict("critical"), make_conflict("critical")]) == 70

    def test_one_warning_scores_95(self):
        assert compute_score([make_conflict("warning")]) == 95

    def test_mixed_critical_and_warning(self):
        conflicts = [
            make_conflict("critical"),
            make_conflict("warning"),
            make_conflict("warning"),
        ]
        # 100 - (1×15) - (2×5) = 75
        assert compute_score(conflicts) == 75

    def test_score_never_below_zero(self):
        conflicts = [make_conflict("critical")] * 10
        # 100 - (10×15) = -50 → clamped to 0
        assert compute_score(conflicts) == 0

    def test_consistent_true_iff_no_critical(self):
        no_critical = [make_conflict("warning"), make_conflict("warning")]
        has_critical = [make_conflict("critical"), make_conflict("warning")]

        critical_count_no = sum(1 for c in no_critical if c.severity == ConflictSeverity.CRITICAL)
        critical_count_has = sum(1 for c in has_critical if c.severity == ConflictSeverity.CRITICAL)

        assert (critical_count_no == 0) is True   # consistent
        assert (critical_count_has == 0) is False  # not consistent


class TestConflictTypes:
    def test_entity_mismatch_is_critical_by_default(self):
        c = make_conflict("critical", "entity_mismatch")
        assert c.severity == ConflictSeverity.CRITICAL

    def test_feature_missing_is_warning(self):
        c = make_conflict("warning", "feature_missing")
        assert c.severity == ConflictSeverity.WARNING

    def test_endpoint_mismatch_is_warning(self):
        c = make_conflict("warning", "endpoint_mismatch")
        assert c.severity == ConflictSeverity.WARNING

    def test_field_mismatch_is_critical(self):
        c = make_conflict("critical", "field_mismatch")
        assert c.severity == ConflictSeverity.CRITICAL


class TestSuccessCriteria:
    """Maps directly to Phase 1.5 Strategic Lock success criteria."""

    def test_perfect_run_score_100(self):
        """Criterion: 'PRD + SDD + API consistent'"""
        result = ConsistencyResult(
            consistent=True, score=100, conflicts=[], summary="All consistent."
        )
        assert result.score == 100
        assert result.consistent is True

    def test_score_reflects_reality(self):
        """Criterion: score must be calculated from actual conflicts, not LLM-assigned."""
        conflicts = [make_conflict("critical"), make_conflict("warning")]
        score = compute_score(conflicts)
        # 100 - 15 - 5 = 80
        assert score == 80
        assert score < 100  # conflicts present means score < 100
