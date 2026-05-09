"""Unit tests for the ai_identify service (parsing & MIME utilities)."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.ai_identify import (
    ALLOWED_MIME_TYPES,
    _parse_response,
    base_mime,
)


# ── base_mime ────────────────────────────────────────────────────────────────

def test_base_mime_strips_codec_params() -> None:
    assert base_mime("audio/webm;codecs=opus") == "audio/webm"

def test_base_mime_strips_whitespace() -> None:
    assert base_mime("  audio/wav  ") == "audio/wav"

def test_base_mime_plain_type_unchanged() -> None:
    assert base_mime("audio/mp4") == "audio/mp4"


# ── ALLOWED_MIME_TYPES ───────────────────────────────────────────────────────

def test_webm_allowed() -> None:
    assert "audio/webm" in ALLOWED_MIME_TYPES

def test_m4a_allowed() -> None:
    assert "audio/mp4" in ALLOWED_MIME_TYPES

def test_unsupported_type_not_allowed() -> None:
    assert "video/mp4" not in ALLOWED_MIME_TYPES


# ── _parse_response ──────────────────────────────────────────────────────────

def test_parse_clean_json() -> None:
    raw = '{"artist": "Pink Floyd", "title": "Another Brick in the Wall", "confidence": 80}'
    result = _parse_response(raw)
    assert result["artist"] == "Pink Floyd"
    assert result["confidence"] == 80

def test_parse_strips_markdown_fences() -> None:
    raw = '```json\n{"artist": "A", "title": "B", "confidence": 70}\n```'
    result = _parse_response(raw)
    assert result["title"] == "B"

def test_parse_extracts_json_from_prose() -> None:
    raw = 'Here is the result: {"artist": "X", "title": "Y", "confidence": 50} — enjoy!'
    result = _parse_response(raw)
    assert result["artist"] == "X"

def test_parse_not_found_error() -> None:
    result = _parse_response('{"error": "not_found"}')
    assert "error" in result

def test_parse_raises_on_garbage() -> None:
    with pytest.raises(ValueError):
        _parse_response("This is not JSON at all.")


# ── identify_melody (mocked Gemini) ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_identify_melody_success() -> None:
    from app.services.ai_identify import identify_melody

    gemini_reply = json.dumps({"artist": "Pink Floyd", "title": "Comfortably Numb", "confidence": 82})

    with (
        patch("app.services.ai_identify.settings") as mock_settings,
        patch("app.services.ai_identify.asyncio.to_thread", new_callable=AsyncMock) as mock_thread,
    ):
        mock_settings.GEMINI_API_KEY = "fake-key"
        mock_settings.GEMINI_MODEL = "gemini-test"
        mock_thread.return_value = gemini_reply

        result = await identify_melody(b"\x00" * 1024, "audio/webm")

    assert result["artist"] == "Pink Floyd"
    assert result["confidence"] == 82


@pytest.mark.asyncio
async def test_identify_melody_not_found() -> None:
    from app.services.ai_identify import identify_melody

    with (
        patch("app.services.ai_identify.settings") as mock_settings,
        patch("app.services.ai_identify.asyncio.to_thread", new_callable=AsyncMock) as mock_thread,
    ):
        mock_settings.GEMINI_API_KEY = "fake-key"
        mock_settings.GEMINI_MODEL = "gemini-test"
        mock_thread.return_value = '{"error": "not_found"}'

        result = await identify_melody(b"\x00" * 1024, "audio/webm")

    assert "error" in result


@pytest.mark.asyncio
async def test_identify_melody_requires_api_key() -> None:
    from app.services.ai_identify import identify_melody

    with patch("app.services.ai_identify.settings") as mock_settings:
        mock_settings.GEMINI_API_KEY = None

        with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
            await identify_melody(b"\x00" * 1024, "audio/webm")
