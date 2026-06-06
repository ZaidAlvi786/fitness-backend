"""Coaching endpoint with the LLM provider mocked: happy path, malformed-output → 502, rate limit."""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient

from app.api.deps import get_llm_provider, get_rate_limiter
from app.core.security import get_current_user
from app.schemas.auth import AuthenticatedUser
from app.services.rate_limit import RateLimiter

_VALID_USER = AuthenticatedUser(id="u")

_VALID_BODY = {
    "timezone": "UTC",
    "goal": "STAY_ACTIVE",
    "daily_summaries": [
        {"epoch_day": 20000, "steps": 8000, "active_minutes": 40, "calories": 420, "distance_km": 6.1}
    ],
    "recent_sessions": [],
}

_CANNED = (
    '{"headline":"Strong, steady week",'
    '"insights":[{"title":"Keep the streak","body":"Steps are trending up — hold the pace.",'
    '"category":"PERFORMANCE"}]}'
)


class _FakeProvider:
    def __init__(self, text: str) -> None:
        self._text = text

    async def complete(self, *, system: str, user: str, max_tokens: int) -> str:
        return self._text


def _override(app: Any, provider_text: str, limiter: RateLimiter | None = None) -> None:
    app.dependency_overrides[get_current_user] = lambda: _VALID_USER
    app.dependency_overrides[get_rate_limiter] = lambda: limiter or RateLimiter(100)
    app.dependency_overrides[get_llm_provider] = lambda: _FakeProvider(provider_text)


async def test_insights_happy_path(client: AsyncClient, app: Any) -> None:
    _override(app, _CANNED)
    resp = await client.post("/api/v1/coaching/insights", json=_VALID_BODY)
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()
    assert data["headline"] == "Strong, steady week"
    assert data["insights"][0]["category"] == "PERFORMANCE"
    assert "generated_at" in data


async def test_malformed_llm_output_is_502(client: AsyncClient, app: Any) -> None:
    _override(app, "this is not json")
    resp = await client.post("/api/v1/coaching/insights", json=_VALID_BODY)
    app.dependency_overrides.clear()
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "upstream_error"


async def test_rate_limit_returns_429(client: AsyncClient, app: Any) -> None:
    shared = RateLimiter(1)
    _override(app, _CANNED, limiter=shared)
    first = await client.post("/api/v1/coaching/insights", json=_VALID_BODY)
    second = await client.post("/api/v1/coaching/insights", json=_VALID_BODY)
    app.dependency_overrides.clear()
    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "rate_limited"
