"""
Marshal Engine v1 — Entity Extractor

Reads a generated PRD and extracts the EntityManifest:
  - canonical entity names from the Glossary section
  - entity definitions
  - feature names from the Features section

Uses upshalter/light (fast + cheap) since this is a structured extraction
task, not a creative generation task.

Falls back to an empty manifest on any failure — the pipeline continues,
but without entity-level constraint enforcement.

Imports fixed for backend/app/services/ package location.
"""
import json
import logging
import re
from pathlib import Path

import httpx

from ..models.v1_schemas import EntityManifest

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "entity_extract.txt"


class EntityExtractor:
    """
    Extracts a structured EntityManifest from a generated PRD.

    Designed to be fast and cheap:
    - Uses upshalter/light (not upshalter/smart)
    - Small output (JSON only, ~500 tokens max)
    - Falls back gracefully on any failure

    The manifest is the single most important data structure in the pipeline.
    It is the ground truth that all subsequent validation is based on.
    """

    MODEL = "upshalter/light"
    MAX_TOKENS = 600
    TIMEOUT = 45.0

    def __init__(self, llm_gateway_url: str):
        self.llm_gateway_url = llm_gateway_url
        self._prompt = PROMPT_PATH.read_text(encoding="utf-8")

    async def extract(self, prd_content: str, session_id: str) -> EntityManifest:
        """
        Extract EntityManifest from PRD. Always returns a manifest.
        On failure, returns an empty manifest with extraction_error set.
        """
        logger.info(f"[{session_id}] EntityExtractor: extracting from PRD")

        # Fast path: try regex extraction first (no LLM cost)
        manifest = self._regex_extract(prd_content)
        if manifest.has_entities:
            logger.info(
                f"[{session_id}] EntityExtractor: regex found {len(manifest.canonical_names)} entities"
            )
            return manifest

        # Slow path: LLM extraction
        logger.info(f"[{session_id}] EntityExtractor: regex found nothing, using LLM")
        return await self._llm_extract(prd_content, session_id)

    def _regex_extract(self, prd_content: str) -> EntityManifest:
        """
        Fast extraction using regex patterns on the PRD markdown.
        Looks for Glossary section with table rows or bold entity names.
        """
        canonical_names = []
        definitions = {}
        features = []

        # Extract from Glossary table: find **Bold** names in table rows
        glossary_pattern = re.compile(
            r'\|\s*[^|]*?\|\s*\*\*([A-Z][A-Za-z0-9]+(?:\s[A-Z][A-Za-z0-9]+)*)\*\*\s*\|\s*([^|]+?)\s*\|',
            re.MULTILINE
        )
        for match in glossary_pattern.finditer(prd_content):
            name = match.group(1).strip()
            definition = match.group(2).strip()
            if name and name not in canonical_names:
                canonical_names.append(name)
                definitions[name] = definition

        # Also look for glossary table with entity in first column
        alt_pattern = re.compile(
            r'\|\s*\*\*([A-Z][A-Za-z0-9]+(?:\s[A-Z][A-Za-z0-9]+)*)\*\*\s*\|\s*([^|]+?)\s*\|',
            re.MULTILINE
        )
        for match in alt_pattern.finditer(prd_content):
            name = match.group(1).strip()
            if name not in canonical_names:
                definition = match.group(2).strip()
                canonical_names.append(name)
                definitions[name] = definition

        # Extract feature names from "### Feature:" or "Feature: " headings
        feature_pattern = re.compile(
            r'###\s+Feature:\s+(.+?)$|^Feature:\s+(.+?)$',
            re.MULTILINE
        )
        for match in feature_pattern.finditer(prd_content):
            feature = (match.group(1) or match.group(2) or "").strip()
            if feature and feature not in features:
                features.append(feature)

        return EntityManifest(
            canonical_names=canonical_names,
            definitions=definitions,
            features=features,
        )

    async def _llm_extract(self, prd_content: str, session_id: str) -> EntityManifest:
        """LLM-based extraction as fallback."""
        prompt = self._prompt + "\n\n" + prd_content
        payload = {
            "model": self.MODEL,
            "max_tokens": self.MAX_TOKENS,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        }

        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                response = await client.post(
                    f"{self.llm_gateway_url}/v1/chat/completions",
                    json=payload,
                )
                response.raise_for_status()

            raw = response.json()["choices"][0]["message"]["content"]
            data = self._parse_json(raw)

            if "error" in data:
                logger.warning(f"[{session_id}] EntityExtractor LLM returned error: {data['error']}")
                return EntityManifest(extraction_error=data["error"])

            manifest = EntityManifest(
                canonical_names=data.get("canonical_names", []),
                definitions=data.get("definitions", {}),
                features=data.get("features", []),
            )
            logger.info(
                f"[{session_id}] EntityExtractor LLM: {len(manifest.canonical_names)} entities, "
                f"{len(manifest.features)} features"
            )
            return manifest

        except Exception as e:
            logger.error(f"[{session_id}] EntityExtractor failed: {e}")
            return EntityManifest(
                extraction_error=str(e),
                canonical_names=[],
                definitions={},
                features=[],
            )

    @staticmethod
    def _parse_json(raw: str) -> dict:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"```\w*\n?", "", raw).strip()
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        return json.loads(raw)
