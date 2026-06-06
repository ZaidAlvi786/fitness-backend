"""Liveness + readiness. Unauthenticated by design (load balancers / k8s probes)."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings
from app.db.session import get_engine_health
from app.schemas.common import HealthStatus, ReadyStatus

router = APIRouter(tags=["health"])

_VERSION = "0.1.0"


@router.get("/health", response_model=HealthStatus)
async def health() -> HealthStatus:
    settings = get_settings()
    return HealthStatus(status="ok", environment=settings.environment.value, version=_VERSION)


@router.get("/ready", response_model=ReadyStatus)
async def ready() -> ReadyStatus:
    db_ok = await get_engine_health()
    return ReadyStatus(status="ok" if db_ok else "degraded", database=db_ok)
