"""
In-process YouTube URL resolver (Feature 1: fast playback).

Uses the yt-dlp Python API to turn a video id into a direct googlevideo audio URL
without spawning a subprocess per play. Results are cached in memory for
``YTDLP_RESOLVED_URL_TTL_SEC`` seconds so repeat plays / prefetches skip the
resolve roundtrip entirely.

The resolver is intentionally defensive: any exception yields ``None`` so the
caller can fall back to the legacy subprocess pipeline in ``streamer.py``.
"""

from __future__ import annotations

import asyncio
import random
import shlex
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.config import settings
from app.utils.logger import setup_logger

_logger = setup_logger(__name__)


@dataclass(frozen=True)
class ResolvedFormat:
    """Direct audio URL plus minimal metadata needed to pick a container."""

    video_id: str
    url: str
    ext: str  # e.g. "webm", "m4a", "mp4"
    acodec: str  # e.g. "opus", "mp4a.40.2", "aac"
    http_headers: Dict[str, str]
    # Monotonic deadline after which the entry is considered expired for our cache.
    # The underlying googlevideo URL usually lives longer, but we re-resolve early
    # to stay ahead of 403s.
    expires_at: float

    @property
    def is_opus(self) -> bool:
        return "opus" in (self.acodec or "").lower()

    @property
    def is_aac(self) -> bool:
        codec = (self.acodec or "").lower()
        return codec.startswith("mp4a") or codec == "aac"

    @property
    def browser_safe_codec(self) -> bool:
        """True when we can stream-copy straight to the browser."""
        return self.is_opus or self.is_aac


_cache_lock = threading.Lock()
_cache: Dict[str, ResolvedFormat] = {}

# A single YoutubeDL instance is cheap to keep around and avoids re-importing all
# extractors on every call. It is also thread-safe for ``extract_info`` with
# ``download=False`` in practice (yt-dlp serializes network calls internally).
_ydl_lock = threading.Lock()
_ydl_instance: Any | None = None


def _build_ydl_opts() -> Dict[str, Any]:
    clients = (settings.YTDLP_YOUTUBE_PLAYER_CLIENT or "tv,web,mweb").strip()
    if not clients:
        clients = "tv,web,mweb"
    opts: Dict[str, Any] = {
        # Audio-only, prefer m4a (AAC) then opus; fall back to generic bestaudio.
        "format": "bestaudio[ext=m4a]/bestaudio[acodec=opus]/bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extractor_args": {"youtube": {"player_client": clients.split(",")}},
    }
    cookies = (settings.YTDLP_COOKIES_FILE or "").strip()
    if cookies:
        opts["cookiefile"] = cookies
    # Opportunistically honor common YTDLP_EXTRA_ARGS values that map to YoutubeDL kwargs.
    extra = (settings.YTDLP_EXTRA_ARGS or "").strip()
    if extra:
        try:
            tokens = shlex.split(extra)
        except ValueError:
            tokens = []
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok in ("--geo-bypass",):
                opts["geo_bypass"] = True
                i += 1
                continue
            if tok in ("--source-address",) and i + 1 < len(tokens):
                opts["source_address"] = tokens[i + 1]
                i += 2
                continue
            if tok in ("--proxy",) and i + 1 < len(tokens):
                opts["proxy"] = tokens[i + 1]
                i += 2
                continue
            i += 1
    return opts


def _get_ydl() -> Any:
    global _ydl_instance
    if _ydl_instance is not None:
        return _ydl_instance
    with _ydl_lock:
        if _ydl_instance is not None:
            return _ydl_instance
        # Import lazily so tests that don't touch YouTube don't need yt-dlp importable.
        from yt_dlp import YoutubeDL  # type: ignore[import-untyped]

        _ydl_instance = YoutubeDL(_build_ydl_opts())
        return _ydl_instance


def _peek_cache(video_id: str) -> Optional[ResolvedFormat]:
    now = time.monotonic()
    with _cache_lock:
        entry = _cache.get(video_id)
        if entry is None:
            return None
        if now > entry.expires_at:
            _cache.pop(video_id, None)
            return None
        return entry


def _store_cache(entry: ResolvedFormat) -> None:
    with _cache_lock:
        _cache[entry.video_id] = entry


def invalidate(video_id: str) -> None:
    """Drop a cached resolution (call after a 403/410 from googlevideo)."""
    with _cache_lock:
        _cache.pop(video_id, None)


def _pick_audio_format(info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Pick an audio-only format. Prefer m4a (AAC), then opus, then any best."""
    formats = info.get("formats") or []
    # yt-dlp sometimes flattens a single chosen format into ``url``/``acodec``/``ext``.
    if not formats and info.get("url"):
        return info

    def _is_audio_only(f: Dict[str, Any]) -> bool:
        if f.get("acodec") in (None, "none"):
            return False
        return f.get("vcodec") in (None, "none")

    audio = [f for f in formats if _is_audio_only(f)]
    if not audio:
        # Fall back to anything with audio, even if it also has video.
        audio = [f for f in formats if f.get("acodec") not in (None, "none")]
    if not audio:
        return None

    def _score(f: Dict[str, Any]) -> tuple[int, int]:
        ext = (f.get("ext") or "").lower()
        codec = (f.get("acodec") or "").lower()
        pref = 0
        if ext == "m4a" or codec.startswith("mp4a") or codec == "aac":
            pref = 3
        elif codec == "opus" or ext == "webm":
            pref = 2
        else:
            pref = 1
        abr = int(f.get("abr") or f.get("tbr") or 0)
        return (pref, abr)

    audio.sort(key=_score, reverse=True)
    return audio[0]


def _resolve_sync(video_id: str) -> Optional[ResolvedFormat]:
    """Blocking resolution using the YoutubeDL Python API."""
    try:
        ydl = _get_ydl()
        url = f"https://www.youtube.com/watch?v={video_id}"
        info = ydl.extract_info(url, download=False)
    except Exception:  # pylint: disable=broad-exception-caught
        _logger.exception("yt_resolver: extract_info failed for %s", video_id)
        return None

    if not isinstance(info, dict):
        _logger.warning("yt_resolver: extract_info returned non-dict for %s", video_id)
        return None

    fmt = _pick_audio_format(info)
    if not fmt or not fmt.get("url"):
        _logger.warning("yt_resolver: no audio format found for %s", video_id)
        return None

    ttl = max(60, int(settings.YTDLP_RESOLVED_URL_TTL_SEC))
    # Add +/-10% jitter so we don't stampede re-resolve on shared popular tracks.
    jitter = random.uniform(-0.1, 0.1) * ttl
    return ResolvedFormat(
        video_id=video_id,
        url=str(fmt["url"]),
        ext=str(fmt.get("ext") or "").lower(),
        acodec=str(fmt.get("acodec") or "").lower(),
        http_headers={str(k): str(v) for k, v in (fmt.get("http_headers") or {}).items()},
        expires_at=time.monotonic() + ttl + jitter,
    )


async def resolve(video_id: str, *, force_refresh: bool = False) -> Optional[ResolvedFormat]:
    """Return a cached or freshly-resolved direct audio URL for ``video_id``."""
    if not video_id:
        return None
    if not force_refresh:
        cached = _peek_cache(video_id)
        if cached is not None:
            return cached

    t0 = time.monotonic()
    resolved = await asyncio.to_thread(_resolve_sync, video_id)
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    if resolved is None:
        _logger.info("yt_resolver: miss video_id=%s elapsed_ms=%d", video_id, elapsed_ms)
        return None

    _store_cache(resolved)
    _logger.info(
        "yt_resolver: resolved video_id=%s ext=%s acodec=%s elapsed_ms=%d",
        video_id,
        resolved.ext,
        resolved.acodec,
        elapsed_ms,
    )
    return resolved
