"""Resolve the public base URL for the versioned JSON API."""
from starlette.requests import Request

from app.api_constants import API_V1_PREFIX
from app.config import settings


def api_v1_base_url(request: Request) -> str:
    """
    Absolute base for JSON API paths (no trailing slash), e.g. https://host/api/v1.
    """
    if settings.PUBLIC_API_BASE_URL:
        root = settings.PUBLIC_API_BASE_URL.rstrip("/")
        return f"{root}{API_V1_PREFIX}"
    return str(request.base_url).rstrip("/") + API_V1_PREFIX
