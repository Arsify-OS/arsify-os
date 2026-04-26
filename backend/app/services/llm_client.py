"""
LLMClient — shared HTTP client for LiteLLM / or_gateway calls.

All agents use this. Single responsibility: POST to /v1/chat/completions
and return the text content. No prompt logic here.
"""

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT  = 120.0
DEFAULT_MODEL    = "upshalter/smart"


class LLMClient:
    """Thin wrapper around or_gateway's OpenAI-compatible endpoint."""

    def __init__(self, gateway_url: str):
        self.gateway_url = gateway_url.rstrip("/")

    async def complete(
        self,
        system:     str,
        user:       str,
        max_tokens: int,
        session_id: str,
        model:      str = DEFAULT_MODEL,
        timeout:    float = DEFAULT_TIMEOUT,
        response_format: Optional[dict] = None,
    ) -> str:
        """
        POST /v1/chat/completions. Returns the assistant message content string.
        Raises httpx.HTTPStatusError on non-2xx. Raises ValueError on empty response.
        """
        payload: dict = {
            "model":      model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
        }
        if response_format:
            payload["response_format"] = response_format

        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                response = await client.post(
                    f"{self.gateway_url}/v1/chat/completions",
                    json=payload,
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.error(
                    f"[{session_id}] LLM HTTP error {exc.response.status_code}: "
                    f"{exc.response.text[:200]}"
                )
                raise
            except httpx.RequestError as exc:
                logger.error(f"[{session_id}] LLM connection error: {exc}")
                raise

        data    = response.json()
        content = data["choices"][0]["message"]["content"]

        if not content or len(content.strip()) < 100:
            raise ValueError(
                f"[{session_id}] LLM returned suspiciously short response "
                f"({len(content)} chars)"
            )

        return content.strip()
