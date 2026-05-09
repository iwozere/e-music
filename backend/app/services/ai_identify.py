"""Gemini-backed melody/hum identification service."""
from __future__ import annotations

import asyncio
import json
import re

from google import genai
from google.genai import types

from app.config import settings
from app.utils.logger import setup_logger

_logger = setup_logger(__name__)

ALLOWED_MIME_TYPES: frozenset[str] = frozenset({
    "audio/wav",
    "audio/x-wav",
    "audio/mpeg",
    "audio/mp4",
    "audio/x-m4a",
    "audio/aac",
    "audio/opus",
    "audio/webm",
    "audio/ogg",
})

_PROMPT = (
    "You are a music identification expert specializing in melody recognition from humming and singing. "
    "Listen carefully to the melodic contour, note intervals, and rhythm in the attached audio clip. "
    "Identify the ONE song that best matches this specific melody. "
    "Be conservative: if the melody is unclear or ambiguous, return a low confidence score or not_found. "
    "Do NOT guess a famous song just because humming is present — only return high confidence "
    "when the melodic pattern is distinctive and unambiguous. "
    'Return ONLY a JSON object: {"artist": "string", "title": "string", "confidence": 0-100}. '
    'If you cannot confidently identify the song, return {"error": "not_found"}.'
)


def base_mime(content_type: str) -> str:
    """Strip codec params: 'audio/webm;codecs=opus' → 'audio/webm'."""
    return content_type.split(";")[0].strip().lower()


def _parse_response(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(ln for ln in lines if not ln.startswith("```")).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r'\{[\s\S]*\}', text)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Cannot parse Gemini response as JSON: {text!r}")


def _call_gemini_sync(audio_bytes: bytes, mime_type: str) -> str:
    """Blocking Gemini call — run via asyncio.to_thread."""
    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    audio_part = types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)
    response = client.models.generate_content(
        model=settings.GEMINI_MODEL,
        contents=[audio_part, _PROMPT],
    )
    return response.text


async def identify_melody(audio_bytes: bytes, mime_type: str) -> dict:
    """
    Send audio inline to Gemini and return parsed identification result.
    Raises RuntimeError if GEMINI_API_KEY is not set.
    Any Gemini SDK exception propagates to the caller (logged in the router).
    """
    if not settings.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    try:
        raw_text = await asyncio.to_thread(_call_gemini_sync, audio_bytes, mime_type)
    except Exception as exc:
        _logger.error("Gemini API call failed (%s): %s", type(exc).__name__, exc)
        raise

    _logger.info("Gemini raw response: %s", raw_text)
    result = _parse_response(raw_text)
    _logger.info("Gemini parsed result: %s", result)
    if "confidence" in result:
        result["confidence"] = int(result["confidence"])
    return result
