"""FastAPI application factory: config, logging, middleware, routers, exception handlers, lifespan."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import httpx
import sentry_sdk
from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.v1 import health
from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger, request_id_ctx
from app.db.session import dispose_engine, init_engine
from app.services.rate_limit import RateLimiter

logger = get_logger(__name__)

# Reject oversized bodies before they're buffered/parsed (coaching payloads are small summaries).
_MAX_BODY_BYTES = 256 * 1024

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    if settings.sentry_dsn:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.environment.value,
            traces_sample_rate=0.1,
        )
    init_engine(settings)
    app.state.http_client = httpx.AsyncClient()
    app.state.rate_limiter = RateLimiter(settings.coaching_rate_limit_per_hour)
    logger.info("startup", environment=settings.environment.value)
    try:
        yield
    finally:
        await app.state.http_client.aclose()
        await dispose_engine()
        logger.info("shutdown")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns/propagates a correlation id, enforces a body-size cap, and adds security headers."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        content_length = request.headers.get("content-length")
        if content_length is not None and content_length.isdigit() and int(content_length) > _MAX_BODY_BYTES:
            return Response(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_ctx.set(rid)
        try:
            response = await call_next(request)
        finally:
            request_id_ctx.reset(token)
        response.headers["x-request-id"] = rid
        for header, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        return response


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="Momentum Backend",
        version="0.1.0",
        summary="LLM coaching, analytics aggregation, and integrations over Supabase Postgres.",
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
    )

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-Id"],
    )

    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(api_router)
    return app


app = create_app()
