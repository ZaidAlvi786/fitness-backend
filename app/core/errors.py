"""Typed application errors and their FastAPI handlers.

Every failure the client can see is one of these, serialized to a consistent [ErrorResponse]. Raw
stack traces and unexpected exceptions are never leaked — they become a generic 500.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.logging import get_logger

logger = get_logger(__name__)


class ErrorDetail(BaseModel):
    code: str = Field(description="Stable machine-readable error code")
    message: str = Field(description="Human-readable, safe-to-display message")
    detail: Any | None = Field(default=None, description="Optional structured context")


class ErrorResponse(BaseModel):
    error: ErrorDetail


class AppError(Exception):
    """Base for all expected, mapped errors."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "internal_error"

    def __init__(self, message: str, *, detail: Any | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


class AuthError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthorized"


class ForbiddenError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "forbidden"


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class RateLimitError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limited"


class UpstreamError(AppError):
    """A dependency we call (e.g. the LLM provider) failed or timed out."""

    status_code = status.HTTP_502_BAD_GATEWAY
    code = "upstream_error"


def _response(status_code: int, code: str, message: str, detail: Any | None = None) -> JSONResponse:
    body = ErrorResponse(error=ErrorDetail(code=code, message=message, detail=detail))
    return JSONResponse(status_code=status_code, content=body.model_dump(exclude_none=True))


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        # 5xx are unexpected enough to log at error; 4xx are client problems (info).
        log = logger.error if exc.status_code >= 500 else logger.info
        log("app_error", code=exc.code, status=exc.status_code, message=exc.message)
        return _response(exc.status_code, exc.code, exc.message, exc.detail)

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return _response(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "validation_error",
            "Request validation failed",
            detail=exc.errors(),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(_request: Request, exc: Exception) -> JSONResponse:
        # Never leak internals — log the real thing, return an opaque 500.
        logger.error("unhandled_exception", error=str(exc), error_type=type(exc).__name__)
        return _response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "internal_error",
            "An unexpected error occurred",
        )
