"""Coaching service: build a prompt from summarized data, call the LLM, and validate its (untrusted)
output back into our typed [InsightResponse] before it ever reaches the client."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from pydantic import BaseModel, Field, ValidationError

from app.core.errors import UpstreamError
from app.schemas.coaching import Insight, InsightRequest, InsightResponse
from app.services.llm.provider import LLMProvider

SYSTEM_PROMPT = (
    "You are a concise, evidence-minded fitness coach. You receive a JSON summary of a user's recent "
    "activity (daily step/calorie/distance roll-ups and recent workout summaries). Respond with ONLY "
    "a JSON object, no prose, of the form:\n"
    '{"headline": string (<=120 chars), "insights": [{"title": string (<=80), '
    '"body": string (<=400), "category": one of '
    '"PERFORMANCE"|"RECOVERY"|"HYDRATION"|"NUTRITION"|"GENERAL"}]}\n'
    "Provide 1-3 specific, actionable insights grounded in the data. Do not invent metrics that are "
    "not present."
)


class _LLMInsights(BaseModel):
    """The shape we require back from the model (generated_at is added server-side, not trusted)."""

    headline: str = Field(min_length=1, max_length=120)
    insights: list[Insight] = Field(min_length=1, max_length=10)


class CoachingService:
    def __init__(self, provider: LLMProvider, max_tokens: int) -> None:
        self._provider = provider
        self._max_tokens = max_tokens

    async def generate(self, request: InsightRequest) -> InsightResponse:
        user_prompt = self._build_prompt(request)
        raw = await self._provider.complete(
            system=SYSTEM_PROMPT, user=user_prompt, max_tokens=self._max_tokens
        )
        parsed = self._parse(raw)
        return InsightResponse(
            headline=parsed.headline,
            insights=parsed.insights,
            generated_at=datetime.now(UTC),
        )

    @staticmethod
    def _build_prompt(request: InsightRequest) -> str:
        # Send only the validated summary — never raw streams. Pydantic already bounded the sizes.
        return request.model_dump_json()

    @staticmethod
    def _parse(raw: str) -> _LLMInsights:
        payload = _extract_json(raw)
        if payload is None:
            raise UpstreamError("Coaching provider returned unparseable output")
        try:
            return _LLMInsights.model_validate(payload)
        except ValidationError as exc:
            raise UpstreamError("Coaching provider returned malformed insights") from exc


def _extract_json(raw: str) -> dict[str, object] | None:
    """Best-effort: parse the whole string, else the first balanced {...} block."""
    text = raw.strip()
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        value = json.loads(text[start : end + 1])
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        return None
