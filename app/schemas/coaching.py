"""Coaching request/response schemas. Snake_case field names match the Android client's JSON exactly.

The request carries only summarized aggregates (never raw sensor streams). The response is the
contract the Android `CoachingApi` deserializes; it is also what we validate the LLM output against.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class InsightCategory(str, Enum):
    performance = "PERFORMANCE"
    recovery = "RECOVERY"
    hydration = "HYDRATION"
    nutrition = "NUTRITION"
    general = "GENERAL"


class DailySummaryIn(BaseModel):
    epoch_day: int
    steps: int = Field(ge=0)
    active_minutes: int = Field(ge=0)
    calories: int = Field(ge=0)
    distance_km: float = Field(ge=0)


class SessionSummaryIn(BaseModel):
    type: str = Field(min_length=1, max_length=40)
    duration_min: int = Field(ge=0)
    distance_km: float = Field(ge=0)
    calories: int = Field(ge=0)
    avg_heart_rate: int | None = Field(default=None, ge=0, le=300)


class InsightRequest(BaseModel):
    timezone: str = Field(min_length=1, max_length=64)
    goal: str | None = Field(default=None, max_length=40)
    recovery_score: int | None = Field(default=None, ge=0, le=100)
    daily_summaries: list[DailySummaryIn] = Field(max_length=31)
    recent_sessions: list[SessionSummaryIn] = Field(default_factory=list, max_length=20)


class Insight(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    body: str = Field(min_length=1, max_length=400)
    category: InsightCategory = InsightCategory.general


class InsightResponse(BaseModel):
    headline: str = Field(min_length=1, max_length=120)
    insights: list[Insight] = Field(min_length=1, max_length=10)
    generated_at: datetime
