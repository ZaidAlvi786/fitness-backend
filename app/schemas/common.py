"""Shared response schemas."""

from __future__ import annotations

from pydantic import BaseModel


class HealthStatus(BaseModel):
    status: str
    environment: str
    version: str


class ReadyStatus(BaseModel):
    status: str
    database: bool
