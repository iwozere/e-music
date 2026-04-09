import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.request_context import request_id_ctx


class RequestContextMiddleware(BaseHTTPMiddleware):
    """
    Propagate X-Request-ID (client-provided or generated) on request.state, response headers,
    and logging context.
    """

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = rid
        token = request_id_ctx.set(rid)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            request_id_ctx.reset(token)
