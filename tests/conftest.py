"""Test fixtures. Env is set here (before app import) so settings validate; auth is exercised with a
locally-generated RSA keypair instead of a real Supabase project."""

from __future__ import annotations

import json
import os
import time
from collections.abc import AsyncIterator
from typing import Any

# Must be set before importing anything that constructs Settings.
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_JWT_AUDIENCE", "authenticated")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")
os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")

import jwt  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

import app.core.security as security  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.main import create_app  # noqa: E402

TEST_KID = "test-key-1"
TEST_USER_ID = "11111111-1111-1111-1111-111111111111"

_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_private_pem = _private_key.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
)
# A second, unrelated key for forging tokens with the right kid but a bad signature.
_other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_other_pem = _other_key.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
)

_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(_private_key.public_key()))
_jwk.update({"kid": TEST_KID, "use": "sig", "alg": "RS256"})
_public_pyjwk = jwt.PyJWK.from_dict(_jwk)


class _FakeJWKSCache:
    async def get_key(self, kid: str) -> jwt.PyJWK:
        return _public_pyjwk


@pytest.fixture(autouse=True)
def _patch_jwks() -> Any:
    """Point the verifier at our test public key instead of fetching Supabase's JWKS."""
    security._jwks_cache = _FakeJWKSCache()  # type: ignore[assignment]
    yield
    security._jwks_cache = None


def make_token(
    *,
    sub: str = TEST_USER_ID,
    aud: str = "authenticated",
    exp_delta: int = 3600,
    kid: str = TEST_KID,
    forged: bool = False,
) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "sub": sub,
        "aud": aud,
        "role": "authenticated",
        "email": "athlete@example.com",
        "iat": now,
        "exp": now + exp_delta,
    }
    key = _other_pem if forged else _private_pem
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


@pytest.fixture
def settings() -> Any:
    return get_settings()


@pytest.fixture
def app() -> Any:
    return create_app()


@pytest_asyncio.fixture
async def client(app: Any) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
