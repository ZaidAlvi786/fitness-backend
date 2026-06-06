"""Supabase JWT verification — the dependency every protected route relies on.

Supabase (with asymmetric signing keys enabled) signs user JWTs with RS256 and publishes the public
keys at `<url>/auth/v1/.well-known/jwks.json`. We fetch + cache that key set, verify the token's
signature/exp/aud, and extract the user id. No shared secret, and we never mint tokens ourselves —
Supabase is the single identity authority.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings
from app.core.errors import AuthError
from app.core.logging import get_logger
from app.schemas.auth import AuthenticatedUser

logger = get_logger(__name__)

# auto_error=False so a missing/invalid header becomes our typed AuthError, not FastAPI's default 403.
_bearer = HTTPBearer(auto_error=False)


class JWKSCache:
    """Caches Supabase's JWKS with a TTL and refreshes on cache-miss (handles key rotation)."""

    def __init__(self, jwks_url: str, ttl_seconds: float = 600.0, http_timeout: float = 10.0) -> None:
        self._url = jwks_url
        self._ttl = ttl_seconds
        self._http_timeout = http_timeout
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at: float = 0.0

    async def _refresh(self) -> None:
        async with httpx.AsyncClient(timeout=self._http_timeout) as client:
            resp = await client.get(self._url)
            resp.raise_for_status()
            jwk_set = jwt.PyJWKSet.from_dict(resp.json())
        self._keys = {key.key_id: key for key in jwk_set.keys if key.key_id is not None}
        self._fetched_at = time.monotonic()
        logger.info("jwks_refreshed", key_count=len(self._keys))

    async def get_key(self, kid: str) -> jwt.PyJWK:
        stale = (time.monotonic() - self._fetched_at) > self._ttl
        if kid not in self._keys or stale:
            await self._refresh()
        key = self._keys.get(kid)
        if key is None:
            # Unknown kid after a (possibly stale) cache → one forced refresh before giving up.
            await self._refresh()
            key = self._keys.get(kid)
        if key is None:
            raise AuthError("Signing key not found for token")
        return key


_jwks_cache: JWKSCache | None = None


def _cache(settings: Settings) -> JWKSCache:
    global _jwks_cache
    if _jwks_cache is None:
        _jwks_cache = JWKSCache(settings.jwks_url)
    return _jwks_cache


async def verify_token(token: str, settings: Settings) -> AuthenticatedUser:
    """Verify signature + exp + aud and return the caller. Raises [AuthError] on any failure."""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise AuthError("Malformed token") from exc

    kid = header.get("kid")
    if header.get("alg") != "RS256" or not isinstance(kid, str):
        raise AuthError("Unsupported or missing token algorithm")

    signing_key = await _cache(settings).get_key(kid)
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.supabase_jwt_audience,
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("Token has expired") from exc
    except jwt.InvalidAudienceError as exc:
        raise AuthError("Token audience mismatch") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError("Invalid token") from exc

    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub:
        raise AuthError("Token missing subject")

    return AuthenticatedUser(
        id=sub,
        email=claims.get("email") if isinstance(claims.get("email"), str) else None,
        role=claims.get("role") if isinstance(claims.get("role"), str) else None,
    )


async def get_current_user(
    _request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> AuthenticatedUser:
    """FastAPI dependency: authenticate the request, or raise 401."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthError("Missing bearer token")
    return await verify_token(credentials.credentials, settings)
