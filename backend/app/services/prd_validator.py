"""
Marshal Engine v1 — PRD Validator

Validates that the generated PRD has the required structural sections
before passing it to the Architect Agent.

This is a fast, deterministic check — no LLM call.
Regex + string matching on the markdown output.

If validation fails with a critical error (no Glossary, no Features),
the Marshal re-runs the Product Agent once before continuing.
Warnings are logged but do not block the pipeline.

Imports fixed for backend/app/services/ package location.
"""
import logging
import re

from ..models.v1_schemas import PrdValidationResult

logger = logging.getLogger(__name__)

REQUIRED_SECTIONS = [
    "Product Overview",
    "Problem Statement",
    "Key Features",
    "Glossary",
]

RECOMMENDED_SECTIONS = [
    "Target Users",
    "User Flows",
    "Non-Functional Requirements",
    "Out of Scope",
]


class PrdValidator:
    """
    Validates the structural completeness of a generated PRD.

    Critical failures (valid=False):
    - No Glossary section present
    - No Key Features section present
    - Fewer than 2 features found

    Warnings (valid=True but logged):
    - Fewer than 3 entities in Glossary
    - Missing recommended sections
    - Features without acceptance criteria
    """

    def validate(self, prd_content: str, session_id: str) -> PrdValidationResult:
        """Validate PRD structure. Returns PrdValidationResult."""
        missing_sections = []
        warnings = []

        # Check required sections
        for section in REQUIRED_SECTIONS:
            pattern = re.compile(
                rf'#{{1,3}}\s+(?:\d+\.\s+)?{re.escape(section)}',
                re.IGNORECASE
            )
            if not pattern.search(prd_content):
                missing_sections.append(section)

        has_glossary = "Glossary" not in missing_sections
        has_features = "Key Features" not in missing_sections

        # Count entities in Glossary
        entity_count = 0
        if has_glossary:
            entity_count = len(re.findall(
                r'\*\*[A-Z][A-Za-z0-9]+(?:\s[A-Z][A-Za-z0-9]+)*\*\*',
                prd_content
            ))
            if entity_count < 3:
                warnings.append(
                    f"Glossary has only {entity_count} entity/entities. "
                    "Minimum 3 recommended for meaningful consistency checking."
                )

        # Count features
        feature_count = len(re.findall(
            r'###\s+Feature:|^Feature:',
            prd_content,
            re.MULTILINE
        ))
        if has_features and feature_count < 2:
            missing_sections.append("sufficient features (minimum 2)")

        # Check recommended sections
        for section in RECOMMENDED_SECTIONS:
            pattern = re.compile(
                rf'#{{1,3}}\s+(?:\d+\.\s+)?{re.escape(section)}',
                re.IGNORECASE
            )
            if not pattern.search(prd_content):
                warnings.append(f"Recommended section missing: {section}")

        # Check for acceptance criteria
        criteria_count = len(re.findall(r'- \[ \]', prd_content))
        if has_features and feature_count > 0 and criteria_count < feature_count:
            warnings.append(
                f"Only {criteria_count} acceptance criteria found for {feature_count} features. "
                "Each feature should have at least 2."
            )

        is_valid = len(missing_sections) == 0

        result = PrdValidationResult(
            valid=is_valid,
            missing_sections=missing_sections,
            warnings=warnings,
            has_glossary=has_glossary,
            has_features=has_features,
            entity_count=entity_count,
            feature_count=feature_count,
        )

        if not is_valid:
            logger.warning(
                f"[{session_id}] PrdValidator: INVALID — missing: {missing_sections}"
            )
        else:
            logger.info(
                f"[{session_id}] PrdValidator: valid — "
                f"{feature_count} features, {entity_count} entities, "
                f"{len(warnings)} warning(s)"
            )

        for w in warnings:
            logger.info(f"[{session_id}] PrdValidator warning: {w}")

        return result
