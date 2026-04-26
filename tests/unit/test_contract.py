"""
Layer 1 — Contract tests
Verify that the role boundary enforcement mechanisms work correctly.
No LLM calls. Pure Python.
"""
import pytest
from pydantic import ValidationError

from pipeline_engine.core.responsibility_contract import (
    DocumentAgent,
    assert_agent_conformance,
    assert_context_frozen,
)
from pipeline_engine.models.v1_schemas_locked import (
    ContextBundle,
    EntityManifest,
)


# ── ContextBundle frozen enforcement ─────────────────────────────────────────

class TestContextBundleFrozen:
    def make_bundle(self) -> ContextBundle:
        manifest = EntityManifest(
            canonical_names=("Member", "Task"),
            definitions={"Member": "A user.", "Task": "A unit of work."},
            features=("Task Management",),
        )
        return ContextBundle(prd_content="# PRD\n...", entity_manifest=manifest)

    def test_context_bundle_is_frozen(self):
        bundle = self.make_bundle()
        with pytest.raises(ValidationError):
            bundle.sdd_content = "hacked"

    def test_context_bundle_allows_copy_with_update(self):
        bundle = self.make_bundle()
        updated = bundle.model_copy(update={"sdd_content": "# SDD\n..."})
        assert updated.sdd_content == "# SDD\n..."
        # Original is unchanged
        assert bundle.sdd_content is None

    def test_entity_manifest_is_frozen(self):
        manifest = EntityManifest(
            canonical_names=("Member",),
            definitions={"Member": "A user."},
            features=(),
        )
        with pytest.raises(ValidationError):
            manifest.canonical_names = ("Hacked",)

    def test_assert_context_frozen_passes_on_frozen(self):
        bundle = self.make_bundle()
        # Should not raise
        assert_context_frozen(bundle)

    def test_assert_context_frozen_fails_on_mutable(self):
        class MutableContext:
            model_config = {}  # no frozen=True

        with pytest.raises(TypeError, match="not frozen"):
            assert_context_frozen(MutableContext())


# ── DocumentAgent protocol ─────────────────────────────────────────────────

class TestDocumentAgentProtocol:
    def test_conforming_agent_passes_isinstance(self):
        class GoodAgent:
            async def generate(self, context, session_id: str, attempt: int) -> str:
                return "document"

        assert isinstance(GoodAgent(), DocumentAgent)

    def test_nonconforming_agent_fails_isinstance(self):
        class BadAgent:
            def generate(self):  # wrong signature, not async
                return "document"

        # Protocol checks for method existence, not signature at isinstance time
        # But assert_agent_conformance does runtime check
        assert isinstance(BadAgent(), DocumentAgent)  # isinstance only checks presence

    def test_assert_agent_conformance_accepts_good_agent(self):
        class GoodAgent:
            async def generate(self, context, session_id: str, attempt: int) -> str:
                return "document"

        # Should not raise
        assert_agent_conformance(GoodAgent(), "GoodAgent")

    def test_assert_agent_conformance_rejects_no_generate(self):
        class BrokenAgent:
            pass  # no generate method

        with pytest.raises(TypeError, match="does not conform"):
            assert_agent_conformance(BrokenAgent(), "BrokenAgent")


# ── EntityManifest constraint_block ──────────────────────────────────────────

class TestEntityManifestConstraintBlock:
    def test_constraint_block_includes_all_names(self):
        manifest = EntityManifest(
            canonical_names=("Member", "Task", "Project"),
            definitions={
                "Member": "A registered user.",
                "Task": "A unit of work.",
                "Project": "A group of tasks.",
            },
            features=("Task Management", "Project Board"),
        )
        block = manifest.constraint_block()
        assert "Member" in block
        assert "Task" in block
        assert "Project" in block

    def test_constraint_block_includes_features(self):
        manifest = EntityManifest(
            canonical_names=("Task",),
            definitions={"Task": "A unit of work."},
            features=("Task Management", "Reporting"),
        )
        block = manifest.constraint_block()
        assert "Task Management" in block
        assert "Reporting" in block

    def test_constraint_block_includes_field_naming(self):
        manifest = EntityManifest(
            canonical_names=("Member",),
            definitions={"Member": "A registered user."},
            features=(),
        )
        block = manifest.constraint_block()
        assert "member_id" in block

    def test_empty_manifest_returns_safe_string(self):
        manifest = EntityManifest()
        block = manifest.constraint_block()
        assert isinstance(block, str)
        assert len(block) > 0


# ── Planner boundary enforcement (static analysis substitute) ─────────────

class TestPlannerBoundary:
    def test_main_imports_only_marshal(self):
        """
        Verify main.py does not directly import agent classes.
        Reads the actual file and checks for forbidden imports.
        """
        import os
        main_path = os.path.join(
            os.path.dirname(__file__), "../../backend/pipeline_engine/main.py"
        )
        if not os.path.exists(main_path):
            pytest.skip("main.py not found at expected path")

        content = open(main_path).read()

        forbidden = [
            "from .core.product_agent import",
            "from .core.architect_agent import",
            "from .core.consistency_engine import",
            "import ProductAgent",
            "import ArchitectAgent",
        ]
        for pattern in forbidden:
            assert pattern not in content, (
                f"main.py contains forbidden import: '{pattern}'. "
                "Planner must not hold direct agent references."
            )

    def test_main_imports_marshal_v1(self):
        import os
        main_path = os.path.join(
            os.path.dirname(__file__), "../../backend/pipeline_engine/main.py"
        )
        if not os.path.exists(main_path):
            pytest.skip("main.py not found at expected path")

        content = open(main_path).read()
        assert "MarshalV1" in content, (
            "main.py must import MarshalV1, not the v2 Marshal."
        )
