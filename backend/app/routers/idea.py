"""
Idea Router — POST /idea

Pre-pipeline analysis of a user's product brief.
Deterministic: no LLM call. No session created. No state written.

Extracts:
  - Detected entities (noun phrases from brief)
  - Project scope estimate (small / medium / large)
  - Validation warnings (brief too short, no domain detected, etc.)

The Planner calls this endpoint before /pipeline/run to give the user
a lightweight preview of what the pipeline will process.

Rules (enforced):
  - No LLM call
  - No SessionManager access
  - No FileStore access
  - No imports from marshal or agents
"""
import re
import logging
from pydantic import BaseModel, Field

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/idea", tags=["idea"])


# ── Request / Response schemas ─────────────────────────────────────────────────

class IdeaRequest(BaseModel):
    brief: str = Field(..., min_length=10, description="Product idea or brief to analyse")


class IdeaResponse(BaseModel):
    scope:           str            # "small" | "medium" | "large"
    word_count:      int
    detected_nouns:  list[str]      # candidate entity names
    warnings:        list[str]      # non-blocking advisory messages
    ready:           bool           # True if brief meets /pipeline/run minimum length
    min_length_met:  bool
    char_count:      int


# ── Scope heuristic ───────────────────────────────────────────────────────────

_SMALL_KEYWORDS = {
    "simple", "basic", "minimal", "one-page", "single", "lightweight",
    "tiny", "small", "prototype", "demo", "poc", "mvp",
}

_LARGE_KEYWORDS = {
    "enterprise", "platform", "marketplace", "saas", "multi-tenant",
    "scalable", "distributed", "microservice", "ecosystem", "comprehensive",
    "full-stack", "end-to-end", "complete", "large", "complex",
}

_DOMAIN_KEYWORDS = {
    "ecommerce", "shop", "store", "payment", "checkout",
    "chat", "messaging", "notification",
    "auth", "login", "user", "account", "profile",
    "task", "project", "management", "board",
    "analytics", "dashboard", "report", "metric",
    "api", "service", "backend", "frontend", "mobile",
    "blog", "content", "cms",
    "booking", "schedule", "calendar", "appointment",
    "social", "feed", "follow", "like",
}


def _estimate_scope(brief: str, word_count: int) -> str:
    lower = brief.lower()

    # Word count bands (primary signal)
    if word_count < 30:
        base = "small"
    elif word_count < 100:
        base = "medium"
    else:
        base = "large"

    # Keyword override
    words = set(re.findall(r'\b\w+\b', lower))
    if words & _LARGE_KEYWORDS:
        return "large"
    if words & _SMALL_KEYWORDS and base != "large":
        return "small"
    return base


def _extract_candidate_nouns(brief: str) -> list[str]:
    """
    Extract candidate entity names from brief using heuristic patterns.
    Looks for:
      - CamelCase words (UserProfile, TaskManager)
      - Capitalised words that aren't sentence starts
      - Quoted "terms"
    Returns deduplicated list, max 10.
    """
    candidates = []

    # CamelCase / PascalCase words
    for match in re.finditer(r'\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b', brief):
        word = match.group()
        if word not in candidates:
            candidates.append(word)

    # Quoted terms: "term" or 'term'
    for match in re.finditer(r'["\']([A-Za-z][A-Za-z\s]{1,30})["\']', brief):
        term = match.group(1).strip().title()
        if term not in candidates:
            candidates.append(term)

    # Capitalised words after colons or bullets (likely domain nouns)
    for match in re.finditer(r'(?:[:,•\-]\s+)([A-Z][a-z]{2,}\b)', brief):
        word = match.group(1)
        if word not in candidates and word not in {
            "The", "This", "That", "With", "For", "And", "But", "From"
        }:
            candidates.append(word)

    return candidates[:10]


def _build_warnings(brief: str, word_count: int, char_count: int) -> list[str]:
    warnings = []

    if char_count < 50:
        warnings.append(
            f"Brief is only {char_count} characters. "
            "POST /pipeline/run requires at least 50 characters."
        )

    if word_count < 15:
        warnings.append(
            "Brief is very short. Add more context about the target users, "
            "core features, and key entities to get better pipeline output."
        )

    lower = brief.lower()
    domain_words = set(re.findall(r'\b\w+\b', lower))
    if not (domain_words & _DOMAIN_KEYWORDS):
        warnings.append(
            "No recognised domain keywords detected. "
            "Consider mentioning the product type (e.g. task manager, e-commerce, chat app)."
        )

    if len(set(brief.lower().split())) < 10:
        warnings.append(
            "Brief has very low vocabulary diversity. "
            "Expand with feature names, user roles, or technical constraints."
        )

    return warnings


# ── POST /idea ─────────────────────────────────────────────────────────────────

@router.post("", response_model=IdeaResponse)
async def analyse_idea(body: IdeaRequest) -> IdeaResponse:
    """
    Analyse a product brief without starting a pipeline session.

    Returns:
      - scope estimate (small / medium / large)
      - detected candidate entity nouns
      - validation warnings
      - readiness flag for /pipeline/run

    No LLM call. No session created. Deterministic and instant.
    """
    brief = body.brief.strip()
    char_count = len(brief)
    word_count = len(brief.split())

    scope = _estimate_scope(brief, word_count)
    detected_nouns = _extract_candidate_nouns(brief)
    warnings = _build_warnings(brief, word_count, char_count)

    min_length_met = char_count >= 50
    ready = min_length_met

    logger.info(
        f"IdeaAnalyser: scope={scope}, words={word_count}, "
        f"nouns={len(detected_nouns)}, warnings={len(warnings)}, ready={ready}"
    )

    return IdeaResponse(
        scope=scope,
        word_count=word_count,
        detected_nouns=detected_nouns,
        warnings=warnings,
        ready=ready,
        min_length_met=min_length_met,
        char_count=char_count,
    )
