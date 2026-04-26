"""
Marshal Engine v1 — Schema additions
Extends the v2 schemas with EntityManifest and ContextBundle.

Placed at: backend/app/models/v1_schemas.py
Imported by: all v1 services (entity_extractor, prd_validator,
             architect_agent_v1, consistency_engine_v1, marshal_v1_service)
"""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class EntityManifest(BaseModel):
    """
    The canonical entity registry extracted from the PRD Glossary.
    Passed to every Architect Agent call as a hard constraint.
    """
    canonical_names: list[str] = Field(default_factory=list)
    definitions: dict[str, str] = Field(default_factory=dict)
    features: list[str] = Field(default_factory=list)
    extraction_error: Optional[str] = None

    @property
    def has_entities(self) -> bool:
        return len(self.canonical_names) > 0

    def constraint_block(self) -> str:
        """
        Pre-formatted string injected into every Architect prompt.
        Tells the LLM exactly which names are canonical and must not change.
        """
        if not self.has_entities:
            return "(no entity manifest available — proceed with PRD entity names)"

        lines = [
            "═══════════════════════════════════════════════════════════════",
            "ENTITY MANIFEST — HARD CONSTRAINTS (violations trigger rejection)",
            "═══════════════════════════════════════════════════════════════",
            "",
            "The following entity names are CANONICAL. You MUST use them",
            "exactly as written. Any alias, abbreviation, synonym, or",
            "alternative spelling will be flagged as a critical violation.",
            "",
            "CANONICAL ENTITIES:",
        ]

        for name, definition in self.definitions.items():
            lines.append(f"  ▸ {name:<20} — {definition}")

        lines.extend([
            "",
            "FIELD NAMING RULE:",
            "When a field references another entity, derive the field name",
            "from that entity's canonical name.",
            "Examples using entities above:",
        ])

        for name in self.canonical_names[:3]:
            snake = name.lower().replace(" ", "_")
            lines.append(f"  ▸ Reference to {name}: use '{snake}_id' (not any other variant)")

        if self.features:
            lines.extend([
                "",
                "PRD FEATURES TO COVER (every feature needs at least one endpoint):",
            ])
            for feature in self.features:
                lines.append(f"  ▸ {feature}")

        lines.extend([
            "",
            "═══════════════════════════════════════════════════════════════",
            "",
        ])

        return "\n".join(lines)


class PrdValidationResult(BaseModel):
    """Result of Marshal's structural validation of the generated PRD."""
    valid: bool
    missing_sections: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    has_glossary: bool = False
    has_features: bool = False
    entity_count: int = 0
    feature_count: int = 0


class ContextBundle(BaseModel):
    """
    The full context passed between Marshal and agents.
    Built after PRD generation + entity extraction.
    Passed to every subsequent step.
    """
    prd_content: str
    entity_manifest: EntityManifest
    sdd_content: Optional[str] = None
    api_content: Optional[str] = None

    def architect_sdd_context(self, prior_conflicts: list = None) -> str:
        """Assemble the complete context string for the SDD generation call."""
        conflict_section = ""
        if prior_conflicts:
            lines = [
                "CONFLICT CORRECTIONS REQUIRED (from previous attempt):",
                "Fix each of these before generating the new SDD.",
                "",
            ]
            for i, c in enumerate(prior_conflicts, 1):
                severity = c.get("severity", "warning") if isinstance(c, dict) else c.severity
                description = c.get("description", "") if isinstance(c, dict) else c.description
                prd_ref = c.get("prd_reference", "") if isinstance(c, dict) else c.prd_reference
                sdd_ref = c.get("sdd_reference", "") if isinstance(c, dict) else c.sdd_reference
                lines.append(f"{i}. [{str(severity).upper()}] {description}")
                lines.append(f"   PRD says: {prd_ref}")
                lines.append(f"   Document had: {sdd_ref}")
                lines.append("")
            conflict_section = "\n".join(lines) + "\n\n"

        return (
            self.entity_manifest.constraint_block()
            + conflict_section
            + "PRD (source of truth):\n\n"
            + self.prd_content
        )

    def architect_api_context(self) -> str:
        """Assemble the complete context string for the API Spec generation call."""
        return (
            self.entity_manifest.constraint_block()
            + "PRD:\n\n"
            + self.prd_content
            + "\n\n---\n\nSDD:\n\n"
            + (self.sdd_content or "")
        )

    def consistency_context(self) -> dict:
        """Return all three documents and entity names for the consistency check."""
        return {
            "prd_content": self.prd_content,
            "sdd_content": self.sdd_content or "",
            "api_content": self.api_content or "",
            "canonical_names": self.entity_manifest.canonical_names,
        }
