"""Bad request bodies are rejected at the edge with 422 (auth + downstream deps stubbed out)."""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient

from app.api.deps import get_coaching_service, get_rate_limiter
from app.core.security import get_current_user
from app.schemas.auth import AuthenticatedUser
from app.services.rate_limit import RateLimiter

_VALID_USER = AuthenticatedUser(id="u")


def _stub_auth_and_deps(app: Any) -> None:
    app.dependency_overrides[get_current_user] = lambda: _VALID_USER
    app.dependency_overrides[get_rate_limiter] = lambda: RateLimiter(100)
    app.dependency_overrides[get_coaching_service] = lambda: object()  # never reached on bad body


async def test_missing_required_field_is_422(client: AsyncClient, app: Any) -> None:
    _stub_auth_and_deps(app)
    resp = await client.post("/api/v1/coaching/insights", json={"timezone": "UTC"})
    app.dependency_overrides.clear()
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


async def test_out_of_range_field_is_422(client: AsyncClient, app: Any) -> None:
    _stub_auth_and_deps(app)
    body = {"timezone": "UTC", "recovery_score": 150, "daily_summaries": []}
    resp = await client.post("/api/v1/coaching/insights", json=body)
    app.dependency_overrides.clear()
    assert resp.status_code == 422


async def test_negative_steps_is_422(client: AsyncClient, app: Any) -> None:
    _stub_auth_and_deps(app)
    body = {
        "timezone": "UTC",
        "daily_summaries": [
            {"epoch_day": 20000, "steps": -5, "active_minutes": 0, "calories": 0, "distance_km": 0.0}
        ],
    }
    resp = await client.post("/api/v1/coaching/insights", json=body)
    app.dependency_overrides.clear()
    assert resp.status_code == 422
