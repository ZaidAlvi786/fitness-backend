"""AI coaching endpoint. Auth-gated, per-user rate-limited, LLM key server-side."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_coaching_service, get_rate_limiter
from app.core.errors import ErrorResponse
from app.core.security import get_current_user
from app.schemas.auth import AuthenticatedUser
from app.schemas.coaching import InsightRequest, InsightResponse
from app.services.coaching_service import CoachingService
from app.services.rate_limit import RateLimiter

router = APIRouter(prefix="/coaching", tags=["coaching"])


@router.post(
    "/insights",
    response_model=InsightResponse,
    responses={
        401: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
    },
    summary="Generate AI coaching insights from summarized activity",
)
async def generate_insights(
    body: InsightRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    service: CoachingService = Depends(get_coaching_service),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> InsightResponse:
    limiter.check(user.id)
    return await service.generate(body)
