"""Versioned API router — everything under /api/v1."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import aggregation, coaching

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(coaching.router)
api_router.include_router(aggregation.router)
