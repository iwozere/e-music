"""AI Shuffle: Groq-backed music recommendation for Radio Mode."""
from __future__ import annotations

import asyncio
import json
from typing import Dict, List

import httpx

from app.config import settings
from app.services.ytmusic import search_youtube
from app.utils.logger import setup_logger

_logger = setup_logger(__name__)

_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def _format_track_list(tracks: List[Dict]) -> str:
    parts = []
    for t in tracks:
        artist = (t.get("artist") or "Unknown").strip()
        title = (t.get("title") or "Unknown").strip()
        parts.append(f"{artist} - {title}")
    return "; ".join(parts)


async def get_ai_suggestions(tracks: List[Dict]) -> List[Dict[str, str]]:
    """Call Groq with the track sequence and return [{artist, title}] suggestions."""
    if not settings.GROQ_API_KEY:
        _logger.warning("GROQ_API_KEY not configured — AI shuffle unavailable")
        return []

    track_list_str = _format_track_list(tracks)
    prompt = (
        f"I just finished listening to these songs in order: {track_list_str}. "
        "Based on the genre, tempo, and mood of this sequence, suggest 10 new similar tracks "
        "to continue the listening session. "
        'Return ONLY a JSON array with no extra text: [{"artist": "...", "title": "..."}]. '
        "Do not repeat any song from the provided list."
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                _GROQ_URL,
                headers={
                    "Authorization": f"Bearer {settings.GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.GROQ_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.75,
                    "max_tokens": 1024,
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()

            # Strip markdown code fences if the model wraps output
            if content.startswith("```"):
                lines = content.splitlines()
                content = "\n".join(
                    line for line in lines if not line.startswith("```")
                ).strip()

            suggestions = json.loads(content)
            if isinstance(suggestions, list):
                return [
                    s for s in suggestions
                    if isinstance(s, dict) and s.get("artist") and s.get("title")
                ]
    except Exception:
        _logger.exception("Groq AI shuffle request failed")
    return []


async def resolve_suggestions_to_tracks(suggestions: List[Dict[str, str]]) -> List[dict]:
    """Search YouTube Music for each suggestion; return up to 10 track dicts."""
    results: List[dict] = []
    for s in suggestions:
        if len(results) >= 10:
            break
        artist = s.get("artist", "").strip()
        title = s.get("title", "").strip()
        query = f"{artist} {title}".strip()
        if not query:
            continue
        try:
            yt_results = await asyncio.to_thread(search_youtube, query, limit=3)
            if yt_results:
                results.append(yt_results[0])
        except Exception:
            _logger.debug("YouTube search failed for '%s'", query, exc_info=True)
    return results
