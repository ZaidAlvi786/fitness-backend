"""Data access for activity analytics. Queries run on the RLS-scoped session, so results are already
limited to the authenticated user — no manual user_id filtering."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DailyActivityRow


class ActivityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def daily_activity_since(self, from_epoch_day: int) -> list[DailyActivityRow]:
        stmt = (
            select(DailyActivityRow)
            .where(DailyActivityRow.epoch_day >= from_epoch_day)
            .order_by(DailyActivityRow.epoch_day)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
