"""JWT verification: valid / expired / forged / wrong-audience, plus the 401 path on a real route."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.core.errors import AuthError
from app.core.security import verify_token
from tests.conftest import TEST_USER_ID, make_token


async def test_valid_token_returns_user() -> None:
    user = await verify_token(make_token(), get_settings())
    assert user.id == TEST_USER_ID
    assert user.email == "athlete@example.com"


async def test_expired_token_rejected() -> None:
    with pytest.raises(AuthError):
        await verify_token(make_token(exp_delta=-10), get_settings())


async def test_forged_signature_rejected() -> None:
    # Right kid, wrong signing key → signature check must fail.
    with pytest.raises(AuthError):
        await verify_token(make_token(forged=True), get_settings())


async def test_wrong_audience_rejected() -> None:
    with pytest.raises(AuthError):
        await verify_token(make_token(aud="some-other-aud"), get_settings())


async def test_garbage_token_rejected() -> None:
    with pytest.raises(AuthError):
        await verify_token("not-a-jwt", get_settings())


async def test_protected_route_without_token_is_401(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/aggregation/trends")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"
