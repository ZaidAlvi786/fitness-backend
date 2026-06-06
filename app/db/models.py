"""SQLAlchemy ORM models. Read-only here — the client owns writes (direct Supabase CRUD)."""

from __future__ import annotations

from sqlalchemy import BigInteger, Integer
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class DailyActivityRow(Base):
    """Maps the `daily_activity` view. RLS (security_invoker) scopes rows to the caller, so we never
    filter by user_id ourselves — `epoch_day` is a sufficient key within one user's rows."""

    __tablename__ = "daily_activity"

    epoch_day: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    total_steps: Mapped[int] = mapped_column(BigInteger)
    record_count: Mapped[int] = mapped_column(Integer)
