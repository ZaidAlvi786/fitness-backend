"""Pure business logic for activity trends — no IO, so it's trivially unit-testable."""

from __future__ import annotations

from app.db.models import DailyActivityRow
from app.schemas.aggregation import ActivityTrends, DailyActivityPoint, TrendDirection


class AggregationService:
    def compute_trends(self, rows: list[DailyActivityRow], window_days: int) -> ActivityTrends:
        points = [
            DailyActivityPoint(epoch_day=row.epoch_day, total_steps=row.total_steps) for row in rows
        ]
        steps = [p.total_steps for p in points]
        total = sum(steps)
        active_days = sum(1 for s in steps if s > 0)
        average = total / len(steps) if steps else 0.0
        best = max(steps) if steps else 0
        return ActivityTrends(
            window_days=window_days,
            active_days=active_days,
            total_steps=total,
            average_steps=round(average, 1),
            best_day_steps=best,
            trend=self._direction(steps),
            daily=points,
        )

    @staticmethod
    def _direction(steps: list[int]) -> TrendDirection:
        """Compare the back half of the window to the front half (±5% dead-band)."""
        if len(steps) < 4:
            return TrendDirection.flat
        mid = len(steps) // 2
        first = sum(steps[:mid]) / mid
        second = sum(steps[mid:]) / (len(steps) - mid)
        if first == 0:
            return TrendDirection.rising if second > 0 else TrendDirection.flat
        if second > first * 1.05:
            return TrendDirection.rising
        if second < first * 0.95:
            return TrendDirection.falling
        return TrendDirection.flat
