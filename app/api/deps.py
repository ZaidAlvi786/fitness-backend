"""Shared FastAPI dependencies wiring repositories/services to the request scope."""

from __future__ import annotations

import httpx
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_user_session
from app.repositories.activity_repository import ActivityRepository
from app.services.aggregation_service import AggregationService
from app.services.coaching_service import CoachingService
from app.services.llm.provider import GeminiProvider, LLMProvider
from app.services.rate_limit import RateLimiter


def get_http_client(request: Request) -> httpx.AsyncClient:
    client: httpx.AsyncClient = request.app.state.http_client
    return client


def get_rate_limiter(request: Request) -> RateLimiter:
    limiter: RateLimiter = request.app.state.rate_limiter
    return limiter


def get_activity_repository(
    session: AsyncSession = Depends(get_user_session),
) -> ActivityRepository:
    return ActivityRepository(session)


def get_aggregation_service() -> AggregationService:
    return AggregationService()


def get_llm_provider(
    client: httpx.AsyncClient = Depends(get_http_client),
    settings: Settings = Depends(get_settings),
) -> LLMProvider:
    return GeminiProvider(settings, client)


def get_coaching_service(
    provider: LLMProvider = Depends(get_llm_provider),
    settings: Settings = Depends(get_settings),
) -> CoachingService:
    return CoachingService(provider, settings.llm_max_tokens)
