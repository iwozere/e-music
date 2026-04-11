"""Resolve the public base URL for the versioned JSON API."""
from starlette.requests import Request

from app.api_constants import API_V1_PREFIX
from app.config import settings


def _forwarded_api_base(request: Request) -> str | None:
    """
    Prefer proxy headers so URLs stay https behind Cloudflare/Tunnel → HTTP → reverse proxy.
    """
    proto = (
        (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    )
    host = (
        request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    )
    host = host.split(",")[0].strip()
    if not host:
        return None
    if proto not in ("http", "https"):
        if request.headers.get("cf-ray") or request.headers.get("cf-connecting-ip"):
            proto = "https"
        else:
            return None
    return f"{proto}://{host.rstrip('/')}{API_V1_PREFIX}"


def api_v1_base_url(request: Request) -> str:
    """
    Absolute base for JSON API paths (no trailing slash), e.g. https://host/api/v1.
    """
    if settings.PUBLIC_API_BASE_URL:
        root = settings.PUBLIC_API_BASE_URL.rstrip("/")
        return f"{root}{API_V1_PREFIX}"
    forwarded = _forwarded_api_base(request)
    if forwarded:
        return forwarded
    return str(request.base_url).rstrip("/") + API_V1_PREFIX
