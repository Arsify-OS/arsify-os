"""
Mock LLM gateway for integration tests.
Replaces httpx calls to or_gateway with deterministic, instant responses.
Zero cost. Zero latency. Fully controllable.

Usage:
    from tests.integration.mock_llm import MockLLMGateway, patch_llm

    @pytest.mark.asyncio
    async def test_something():
        with patch_llm(responses={"prd": VALID_PRD, "sdd": VALID_SDD}):
            result = await marshal.run(session_id, brief)
"""
import json
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch, MagicMock

from tests.fixtures.sample_prd import (
    VALID_PRD,
    VALID_SDD,
    VALID_API_SPEC,
    BROKEN_SDD_WRONG_ENTITY,
)

# ── Pre-built response sets ────────────────────────────────────────────────

def _chat_response(content: str) -> dict:
    """Wrap a string in the OpenAI-compatible chat completion response format."""
    return {
        "choices": [
            {
                "message": {
                    "content": content,
                    "role": "assistant",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 200},
    }


PERFECT_CONSISTENCY_RESULT = json.dumps({
    "consistent": True,
    "score": 100,
    "conflicts": [],
    "summary": "All entity names match. All features covered. No conflicts.",
})

ONE_CRITICAL_CONSISTENCY_RESULT = json.dumps({
    "consistent": False,
    "score": 85,
    "conflicts": [
        {
            "type": "entity_mismatch",
            "description": "PRD Glossary defines 'Member' but SDD uses 'User'",
            "prd_reference": "Glossary: Member — A registered individual",
            "sdd_reference": "Data Models: User — fields: id, email",
            "severity": "critical",
        }
    ],
    "summary": "One critical entity name mismatch found.",
})

ENTITY_EXTRACT_RESULT = json.dumps({
    "canonical_names": ["Workspace", "Member", "Project", "Task", "AuditLog"],
    "definitions": {
        "Workspace": "A shared environment owned by an organisation.",
        "Member": "A registered individual who belongs to a Workspace.",
        "Project": "A container for Tasks within a Workspace.",
        "Task": "A unit of work within a Project.",
        "AuditLog": "An immutable record of a state change event.",
    },
    "features": ["Task Management", "Workspace Management", "Project Organisation", "Manager Dashboard"],
})


class ResponseSequence:
    """
    Returns different responses per call, in order.
    Allows simulating: PRD call → SDD call → API call → Consistency call.
    """
    def __init__(self, sequence: list[str]):
        self.sequence = sequence
        self.index = 0

    def next(self) -> str:
        if self.index >= len(self.sequence):
            return self.sequence[-1]  # repeat last
        response = self.sequence[self.index]
        self.index += 1
        return response


# ── Mock HTTP client ───────────────────────────────────────────────────────

class MockHttpxResponse:
    """Minimal httpx.Response mock."""
    def __init__(self, content: str, status_code: int = 200):
        self._content = content
        self.status_code = status_code

    def json(self) -> dict:
        return _chat_response(self._content)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


class MockAsyncClient:
    """
    Replaces httpx.AsyncClient for integration tests.
    Returns pre-configured responses in order.
    """
    def __init__(self, response_sequence: ResponseSequence):
        self.sequence = response_sequence

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def post(self, url: str, json: dict = None, **kwargs) -> MockHttpxResponse:
        content = self.sequence.next()
        return MockHttpxResponse(content)


@contextmanager
def patch_llm(
    prd: str = VALID_PRD,
    sdd: str = VALID_SDD,
    api: str = VALID_API_SPEC,
    consistency: str = PERFECT_CONSISTENCY_RESULT,
    entity_extract: str = ENTITY_EXTRACT_RESULT,
    # Override the full sequence if needed
    custom_sequence: list[str] = None,
):
    """
    Context manager that patches httpx.AsyncClient to return mock LLM responses.

    Default sequence: entity_extract → prd → sdd → api → consistency
    (matches the order of LLM calls in MarshalV1._execute)
    """
    if custom_sequence:
        sequence = ResponseSequence(custom_sequence)
    else:
        sequence = ResponseSequence([
            entity_extract,  # EntityExtractor LLM fallback (usually regex handles it)
            prd,             # ProductAgent
            sdd,             # ArchitectAgent SDD
            api,             # ArchitectAgent API
            consistency,     # ConsistencyEngineV1
        ])

    mock_client_class = lambda **kwargs: MockAsyncClient(sequence)

    with patch("httpx.AsyncClient", new=mock_client_class):
        yield sequence
