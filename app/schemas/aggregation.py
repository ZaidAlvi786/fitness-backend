"""Aggregation/analytics response schemas (server-computed, RLS-scoped to the caller)."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class TrendDirection(str, Enum):
    rising = "rising"
    falling = "falling"
    flat = "flat"


class DailyActivityPoint(BaseModel):
    epoch_day: int
    total_steps: int


class ActivityTrends(BaseModel):
    window_days: int = Field(description="Size of the analysis window requested")
    active_days: int = Field(description="Days in the window with any recorded steps")
    total_steps: int
    average_steps: float
    best_day_steps: int
    trend: TrendDirection = Field(description="Direction of the second half vs. the first half")
    daily: list[DailyActivityPoint]
