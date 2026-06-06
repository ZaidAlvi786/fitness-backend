"""LLM provider abstraction + a Google Gemini implementation over async httpx.

Targets Vertex AI in **Express mode** (`aiplatform.googleapis.com`) authenticated with an
`AQ.`-prefixed Express API key — NOT the AI Studio `generativelanguage` endpoint. The request/
response bodies are the standard Gemini `generateContent` shape; only the host + auth differ.

The API key lives only in server-side settings. Calls are async with a hard timeout and bounded
exponential-backoff retries on transient failures; anything terminal surfaces as [UpstreamError] so
the route can degrade gracefully instead of leaking provider internals.
"""

from __future__ import annotations

from typing import Protocol

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import Settings
from app.core.errors import UpstreamError
from app.core.logging import get_logger

logger = get_logger(__name__)

# Vertex AI Express-mode endpoint (AQ.-prefixed key). The model name is interpolated per request.
GEMINI_URL_TEMPLATE = (
    "https://aiplatform.googleapis.com/v1/publishers/google/models/{model}:generateContent"
)


class LLMProvider(Protocol):
    async def complete(self, *, system: str, user: str, max_tokens: int) -> str: ...


class _RetryableUpstream(Exception):
    """Internal marker for transient failures worth retrying."""


class GeminiProvider:
    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client

    @retry(
        retry=retry_if_exception_type((_RetryableUpstream, httpx.TransportError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, max=4),
        reraise=True,
    )
    async def _post(self, payload: dict[str, object]) -> httpx.Response:
        url = GEMINI_URL_TEMPLATE.format(model=self._settings.gemini_model)
        try:
            resp = await self._client.post(
                url,
                headers={
                    "x-goog-api-key": self._settings.gemini_api_key,
                    "content-type": "application/json",
                },
                json=payload,
                timeout=self._settings.llm_timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise _RetryableUpstream("timeout") from exc
        # 429/5xx are transient; retry. 4xx (other) is terminal.
        if resp.status_code in (429,) or resp.status_code >= 500:
            raise _RetryableUpstream(f"status {resp.status_code}")
        return resp

    async def complete(self, *, system: str, user: str, max_tokens: int) -> str:
        # responseMimeType=application/json asks Gemini to emit a bare JSON object, which is exactly
        # what the coaching service parses — no markdown fences to strip.
        payload: dict[str, object] = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "responseMimeType": "application/json",
            },
        }
        try:
            resp = await self._post(payload)
        except (_RetryableUpstream, httpx.TransportError) as exc:
            logger.error("llm_unreachable", error=str(exc))
            raise UpstreamError("Coaching provider is unavailable") from exc

        if resp.status_code >= 400:
            logger.error("llm_error_status", status=resp.status_code)
            raise UpstreamError("Coaching provider returned an error")

        data = resp.json()
        # Gemini generateContent: {"candidates": [{"content": {"parts": [{"text": "..."}]}}], ...}
        candidates = data.get("candidates") if isinstance(data, dict) else None
        if not isinstance(candidates, list) or not candidates:
            raise UpstreamError("Coaching provider returned an empty response")
        content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
        parts = content.get("parts") if isinstance(content, dict) else None
        if not isinstance(parts, list) or not parts:
            raise UpstreamError("Coaching provider returned no content")
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
        if not text.strip():
            raise UpstreamError("Coaching provider returned no text")
        return text
