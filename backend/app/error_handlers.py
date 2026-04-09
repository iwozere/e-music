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
    @app.exception_handler(StarletteHTTPException)
    async def http_exc(request: Request, exc: StarletteHTTPException) -> JSONResponse:
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
    async def rate_limit_exc(request: Request, exc: RateLimitExceeded) -> JSONResponse:
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
    ) -> JSONResponse:
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
    async def unhandled_exc(request: Request, exc: Exception) -> JSONResponse:
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
