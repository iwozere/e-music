"""AI endpoints: hum-to-search melody identification."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from app.config import settings
from app.dependencies import get_current_user
from app.limiter_ext import limiter
from app.models import User
from app.services.ai_identify import ALLOWED_MIME_TYPES, base_mime, identify_melody
from app.services.ytmusic import search_youtube
from app.utils.logger import setup_logger

_logger = setup_logger(__name__)

router = APIRouter(prefix="/ai", tags=["ai"])

_MAX_AUDIO_BYTES = 10 * 1024 * 1024  # 10 MB hard cap


@router.post("/identify")
@limiter.limit("3/minute")
async def identify_track(
    request: Request,
    audio: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
) -> dict:
    if not settings.GEMINI_API_KEY:
        raise HTTPException(status_code=503, detail="Audio identification is not configured")

    mime = base_mime(audio.content_type or "")
    if mime not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported audio format '{mime}'. Use wav, webm, opus, m4a, or mp3.",
        )

    audio_bytes = await audio.read()
    if len(audio_bytes) > _MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Audio file too large (max 10 MB)")
    if not audio_bytes:
        raise HTTPException(status_code=422, detail="Audio file is empty")

    try:
        result = await identify_melody(audio_bytes, mime)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception:
        _logger.exception("identify_melody failed for user %s", current_user.id)
        raise HTTPException(status_code=502, detail="Audio identification service error")

    if "error" in result:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "not_found",
                "message": "Could not identify the melody — try humming a bit louder or longer.",
            },
        )

    confidence = result.get("confidence", 0)
    if confidence < settings.IDENTIFY_MIN_CONFIDENCE:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "low_confidence",
                "message": "Couldn't quite make that out — try humming a bit louder or longer.",
                "confidence": confidence,
            },
        )

    artist = (result.get("artist") or "").strip()
    title = (result.get("title") or "").strip()
    if not artist or not title:
        _logger.error("Gemini returned incomplete metadata: %s", result)
        raise HTTPException(status_code=502, detail="Incomplete response from identification service")

    try:
        yt_results = await asyncio.to_thread(search_youtube, f"{artist} {title}", 3)
    except Exception:
        _logger.exception("YouTube search failed after identification: '%s - %s'", artist, title)
        yt_results = []

    track = yt_results[0] if yt_results else None

    return {
        "artist": artist,
        "title": title,
        "confidence": confidence,
        "remote_id": track["remote_id"] if track else None,
        "thumbnail": track.get("thumbnail") if track else None,
    }
