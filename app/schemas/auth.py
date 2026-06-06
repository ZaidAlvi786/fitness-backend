"""Identity extracted from a verified Supabase JWT."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AuthenticatedUser(BaseModel):
    """The authenticated caller. `id` is the Supabase user id (`auth.uid()`)."""

    id: str = Field(description="Supabase user id (JWT `sub`)")
    email: str | None = Field(default=None)
    role: str | None = Field(default=None)
