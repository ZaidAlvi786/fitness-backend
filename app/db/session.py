"""Async SQLAlchemy engine + an RLS-scoped session dependency.

Key decision (RLS interplay): we connect to Postgres directly (asyncpg) for complex reads, but we
still want Supabase's row-level security to apply. PostgREST normally sets `request.jwt.claims` and
switches to the `authenticated` role so policies keyed on `auth.uid()` work. We replicate that here:
[get_user_session] opens a transaction, sets the verified user's claims + the `authenticated` role
LOCAL to that transaction, and yields the session. So even on a direct connection the user can only
ever see their own rows — no service-role key, no hand-rolled `WHERE user_id = ...` to forget.
"""

from __future__ import annotations

import json
import ssl
from collections.abc import AsyncIterator
from urllib.parse import urlsplit

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings
from app.core.security import get_current_user
from app.schemas.auth import AuthenticatedUser

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", ""}


def _connect_args(database_url: str) -> dict[str, object]:
    """asyncpg connect args. Supabase requires TLS, but the pooler presents a cert outside the public
    CA roots, so we encrypt without CA verification (equivalent to libpq `sslmode=require`). Local
    Postgres needs no SSL, so we skip it there."""
    host = urlsplit(database_url.replace("+asyncpg", "")).hostname or ""
    if host in _LOCAL_HOSTS:
        return {}
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return {"ssl": ctx}


def init_engine(settings: Settings) -> AsyncEngine:
    """Create the engine + sessionmaker once (called from the app lifespan)."""
    global _engine, _sessionmaker
    if _engine is None:
        _engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
            connect_args=_connect_args(settings.database_url),
        )
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


def _maker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        raise RuntimeError("Database engine not initialized")
    return _sessionmaker


async def get_engine_health() -> bool:
    """Lightweight readiness probe — `SELECT 1`."""
    if _engine is None:
        return False
    try:
        async with _engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 — readiness must never raise
        return False


async def get_user_session(
    user: AuthenticatedUser = Depends(get_current_user),
) -> AsyncIterator[AsyncSession]:
    """Yield a session that acts AS the authenticated user, with RLS enforced for the whole request."""
    claims = json.dumps({"sub": user.id, "role": "authenticated"})
    async with _maker()() as session, session.begin():
        # LOCAL to this transaction: scope auth.uid() to the user and drop superuser privileges so
        # RLS is actually evaluated (the owner/superuser role would otherwise bypass it).
        await session.execute(
            text("SELECT set_config('request.jwt.claims', :claims, true)"),
            {"claims": claims},
        )
        await session.execute(text("SET LOCAL ROLE authenticated"))
        yield session
