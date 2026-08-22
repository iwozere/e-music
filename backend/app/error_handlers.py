import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

_logger = logging.getLogger(__name__)


def _headers_with_rid(request: Request) -> dict[str, str]:
    rid = getattr(request.state, "request_id", None)
    if rid:
        return {"X-Request-ID": rid}
    return {}


def register_exception_handlers(app: FastAPI) -> None:
    # Handlers below are only referenced via the `@app.exception_handler(...)`
    # decorator, which Pyright's basic ruleset doesn't recognize as a "use" for
    # function-scoped defs (reportUnusedFunction) — the per-type overloads on
    # `app.exception_handler` are also why these stay decorators rather than
    # plain top-level functions passed to `add_exception_handler`, whose
    # broader `ExceptionHandler` stub type rejects the narrower exc types below.
    @app.exception_handler(StarletteHTTPException)
    async def http_exc(request: Request, exc: StarletteHTTPException) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        if exc.status_code == 404:
            _logger.info(
                "404 Not Found: %s %s [x_forwarded_for=%s client=%s]",
                request.method,
                request.url.path,
                request.headers.get("x-forwarded-for", "-"),
                request.client.host if request.client else "-",
            )
        detail: Any = exc.detail
        if isinstance(detail, str):
            body = {
                "code": f"http_{exc.status_code}",
                "message": detail,
                "detail": None,
            }
        else:
            body = {
                "code": f"http_{exc.status_code}",
                "message": "Request failed",
                "detail": detail,
            }
        return JSONResponse(
            status_code=exc.status_code,
            content=body,
            headers=_headers_with_rid(request),
        )

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_exc(request: Request, exc: RateLimitExceeded) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return JSONResponse(
            status_code=429,
            content={
                "code": "rate_limited",
                "message": str(exc.detail),
                "detail": None,
            },
            headers=_headers_with_rid(request),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exc(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return JSONResponse(
            status_code=422,
            content={
                "code": "validation_error",
                "message": "Invalid request",
                "detail": exc.errors(),
            },
            headers=_headers_with_rid(request),
        )

    @app.exception_handler(Exception)
    async def unhandled_exc(request: Request, exc: Exception) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        rid = getattr(request.state, "request_id", "")
        _logger.exception("Unhandled error [request_id=%s]", rid, exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={
                "code": "internal_error",
                "message": "Internal server error",
                "detail": None,
            },
            headers=_headers_with_rid(request),
        )
