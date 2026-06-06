"""Server-computed activity analytics. RLS scopes all reads to the caller."""

from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_activity_repository, get_aggregation_service
from app.core.errors import ErrorResponse
from app.core.security import get_current_user
from app.repositories.activity_repository import ActivityRepository
from app.schemas.aggregation import ActivityTrends
from app.schemas.auth import AuthenticatedUser
from app.services.aggregation_service import AggregationService

router = APIRouter(prefix="/aggregation", tags=["aggregation"])

_EPOCH = date(1970, 1, 1)


def _today_epoch_day() -> int:
    # Days since 1970-01-01 (UTC). The client uses device-local epoch days; a ±1 day boundary offset
    # is acceptable for a multi-day trend window.
    return (datetime.now(UTC).date() - _EPOCH).days


@router.get(
    "/trends",
    response_model=ActivityTrends,
    responses={401: {"model": ErrorResponse}},
    summary="Daily step trends over a rolling window",
)
async def activity_trends(
    days: int = Query(default=30, ge=1, le=365),
    _user: AuthenticatedUser = Depends(get_current_user),
    repo: ActivityRepository = Depends(get_activity_repository),
    service: AggregationService = Depends(get_aggregation_service),
) -> ActivityTrends:
    from_epoch_day = _today_epoch_day() - (days - 1)
    rows = await repo.daily_activity_since(from_epoch_day)
    return service.compute_trends(rows, days)
