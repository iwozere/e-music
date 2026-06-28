from fastapi import APIRouter, Request

from app.config import settings
from app.public_api import api_v1_base_url

router = APIRouter(prefix="/config", tags=["config"])


@router.get("")
async def get_public_config(request: Request) -> dict:
    """
    Public client configuration (auth + API root). Replaces legacy /auth/config and /system/config.
    """
    return {
        "google_client_id": settings.GOOGLE_CLIENT_ID,
        "api_base_url": api_v1_base_url(request),
        "api_version": "1",
        # Standalone Edition (docs/features-v7.md): the web UI uses these to decide whether to
        # render the Google login (oauth), auto-login the local user (local), or show a password form.
        "profile": settings.APP_PROFILE,
        "auth_mode": settings.auth_mode(),
    }
