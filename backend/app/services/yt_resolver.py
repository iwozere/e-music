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
import contextvars
import random
import re
import shlex
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings
from app.utils.logger import setup_logger

_logger = setup_logger(__name__)


# ---------------------------------------------------------------------------
# Phase timing instrumentation
# ---------------------------------------------------------------------------
# yt-dlp emits a stream of short messages as it walks through the YouTube
# extraction pipeline ("Downloading webpage", "Downloading tv client config",
# "Downloading tv player API JSON", "Decrypting signature", ...). We intercept
# those via yt-dlp's ``logger`` option and record the monotonic-ms offset at
# which each *first* occurrence was observed. The resulting list lets us see
# which phase is actually dominating the ~10 s cold-miss on the Pi.
#
# A shared ``_DispatchLogger`` is installed on the singleton ``YoutubeDL``
# instance; per-call ``_PhaseRecorder``s are dispatched via a contextvar so
# concurrent resolves don't stomp on each other.


@dataclass
class _PhaseEvent:
    name: str   # e.g. "webpage", "client_cfg:tv", "signature"
    ms: int     # offset in ms from resolve start


class _PhaseRecorder:
    """Per-resolve sink for yt-dlp's info/debug/warning messages.

    Records only the *first* occurrence of each known phase to keep the log
    line short. Unknown messages are ignored.
    """

    # Ordered list of (base_name, regex, client_capture_group_or_None).
    # The first match wins, so put more specific patterns before generic ones.
    # Anything that doesn't match falls through to ``_CATCHALL`` below so we
    # still time unknown "Downloading X" messages as ``misc:X``.
    _PATTERNS: List[Tuple[str, "re.Pattern[str]", Optional[int]]] = [
        # ---- initial page + iframe API ----
        ("webpage",       re.compile(r"Downloading webpage",                       re.I), None),
        ("iframe_api",    re.compile(r"Downloading iframe API",                    re.I), None),
        # ---- per-client endpoints ----
        ("client_cfg",    re.compile(r"Downloading (\w+) client config",           re.I), 1),
        ("player_api",    re.compile(r"Downloading (\w+) player API JSON",         re.I), 1),
        ("initial_data",  re.compile(r"Downloading initial data",                  re.I), None),
        # ---- player JS + JS challenges (signature & n-sig) ----
        # Matches both "Downloading player abc123.js" (older yt-dlp) and plain
        # "Downloading player abc123" (newer yt-dlp, no extension). This is
        # placed after ``player_api`` above so "Downloading tv player API JSON"
        # is not misclassified here.
        ("player_js",     re.compile(r"Downloading player\s+\S+",                  re.I), None),
        ("signature",     re.compile(r"(?:Decrypt|Decipher|Extract)\w*\s+signature", re.I), None),
        # "Extracting n function", "Downloading n function code", "Testing n
        # function", "Decrypting nsig", "n-challenge", ... — all bucketed as
        # ``nsig`` since the cost is one logical JS-runtime round-trip.
        ("nsig",          re.compile(
            r"\bn[-\s_]?(?:challenge|decipher|transform|sig)\b"
            r"|(?:Downloading|Extracting|Testing|Decrypting|Deciphering)\s+n(?:sig)?\s+function",
            re.I,
        ), None),
        # ---- PO token (yt-dlp-ejs / pot plugins) ----
        ("po_token",      re.compile(r"\bPO[-\s_]?Token\b|Fetching\s+PO\b",        re.I), None),
        # ---- JS runtime / EJS (yt-dlp-ejs emits these when it invokes Deno) ----
        ("ejs",           re.compile(r"\b(?:yt-dlp-ejs|EJS)\b|\bDeno\b|\bNode\.?js\b", re.I), None),
        # ---- final format selection (emitted by YoutubeDL itself) ----
        ("format_select", re.compile(r"Downloading\s+\d+\s+format",                re.I), None),
    ]

    # Safety-net: any unknown ``<Verb> <thing>`` message still shows up in the
    # timing string as ``misc:<verb>:<thing>``. The verb list covers everything
    # yt-dlp / yt-dlp-ejs typically prints during a resolve; the slug is the
    # first word after the verb (lower-cased, truncated) so future yt-dlp
    # string changes cannot silently re-introduce unexplained multi-second
    # gaps between two named phases.
    _CATCHALL: "re.Pattern[str]" = re.compile(
        r"\b(?P<verb>Downloading|Extracting|Decrypting|Deciphering|Testing|"
        r"Fetching|Running|Solving|Computing|Loading|Executing|Building|"
        r"Parsing|Generating)\s+(?P<slug>[A-Za-z][A-Za-z0-9_\-]{1,31})",
        re.I,
    )

    def __init__(self, *, video_id: str) -> None:
        self.video_id = video_id
        self._t0 = time.monotonic()
        self._events: List[_PhaseEvent] = []
        self._seen_keys: set[str] = set()
        self._clients: List[str] = []

    def _ms(self) -> int:
        return int((time.monotonic() - self._t0) * 1000)

    def _record_message(self, msg: Any) -> None:
        if not isinstance(msg, str) or not msg:
            return
        for base, pat, client_group in self._PATTERNS:
            m = pat.search(msg)
            if not m:
                continue
            client: Optional[str] = None
            if client_group is not None:
                try:
                    client = (m.group(client_group) or "").lower() or None
                except (IndexError, re.error):
                    client = None
            if client and client not in self._clients:
                self._clients.append(client)
            key = f"{base}:{client}" if client else base
            self._record_event(key)
            return

        # No specific pattern matched — try the safety-net catch-all so we
        # still time unknown "<verb> <slug>" messages. Bucketed as
        # ``misc:<verb>:<slug>`` (both lower-cased) so the verb hints at
        # whether this is a network fetch, a CPU-bound decrypt, a JS
        # runtime call, etc. — useful when diagnosing which yt-dlp-ejs step
        # is dominating the resolve.
        cm = self._CATCHALL.search(msg)
        if cm:
            verb = (cm.group("verb") or "").lower()
            slug = (cm.group("slug") or "").lower()
            if verb and slug:
                self._record_event(f"misc:{verb}:{slug}")

    def _record_event(self, key: str) -> None:
        if key in self._seen_keys:
            return  # first-occurrence-only
        self._seen_keys.add(key)
        try:
            self._events.append(_PhaseEvent(name=key, ms=self._ms()))
        except Exception:  # pylint: disable=broad-exception-caught
            pass

    # yt-dlp logger protocol -------------------------------------------------
    def debug(self, msg: Any) -> None:     # noqa: D401 — protocol method
        self._record_message(msg)

    def info(self, msg: Any) -> None:      # noqa: D401
        self._record_message(msg)

    def warning(self, msg: Any) -> None:   # noqa: D401
        self._record_message(msg)

    def error(self, msg: Any) -> None:     # noqa: D401
        # Errors surface as exceptions from ``extract_info``; no need to record.
        return

    # Consumer ---------------------------------------------------------------
    @property
    def events(self) -> List[_PhaseEvent]:
        return list(self._events)

    @property
    def clients(self) -> List[str]:
        return list(self._clients)


_recorder_ctx: contextvars.ContextVar[Optional[_PhaseRecorder]] = contextvars.ContextVar(
    "_yt_resolver_recorder", default=None
)


class _DispatchLogger:
    """yt-dlp logger that forwards every message to the current context's recorder.

    Installed once on the singleton ``YoutubeDL``; ``_PhaseRecorder`` instances
    come and go via ``_recorder_ctx``. If no recorder is bound (unexpected),
    messages are dropped silently — yt-dlp itself still honours ``quiet`` for
    stderr output, so nothing leaks either way.
    """

    def debug(self, msg: Any) -> None:
        r = _recorder_ctx.get()
        if r is not None:
            r.debug(msg)

    def info(self, msg: Any) -> None:
        r = _recorder_ctx.get()
        if r is not None:
            r.info(msg)

    def warning(self, msg: Any) -> None:
        r = _recorder_ctx.get()
        if r is not None:
            r.warning(msg)

    def error(self, msg: Any) -> None:
        r = _recorder_ctx.get()
        if r is not None:
            r.error(msg)


_dispatch_logger = _DispatchLogger()


def _fmt_timing(events: List[_PhaseEvent]) -> str:
    if not events:
        return ""
    # e.g. "webpage@180,client_cfg:tv@260,player_api:tv@3500"
    return ",".join(f"{ev.name}@{ev.ms}" for ev in events)


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
        # Route yt-dlp's chatty extractor messages into our phase recorder so
        # the resolver log line can break the ~10 s cold-miss into phases.
        "logger": _dispatch_logger,
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
            ttl_remaining = max(0, int(cached.expires_at - time.monotonic()))
            _logger.debug(
                "yt_resolver: hit video_id=%s ttl_remaining_s=%d", video_id, ttl_remaining
            )
            return cached

    recorder = _PhaseRecorder(video_id=video_id)
    token = _recorder_ctx.set(recorder)
    t0 = time.monotonic()
    try:
        resolved = await asyncio.to_thread(_resolve_sync, video_id)
    finally:
        _recorder_ctx.reset(token)
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    timing = _fmt_timing(recorder.events)
    clients = ",".join(recorder.clients) if recorder.clients else ""
    extras: List[str] = ["cache=miss"]
    if clients:
        extras.append(f"clients={clients}")
    if timing:
        extras.append(f"timing={timing}")
    extras_str = " ".join(extras)

    if resolved is None:
        _logger.info(
            "yt_resolver: miss video_id=%s elapsed_ms=%d %s",
            video_id, elapsed_ms, extras_str,
        )
        return None

    _store_cache(resolved)
    _logger.info(
        "yt_resolver: resolved video_id=%s ext=%s acodec=%s elapsed_ms=%d %s",
        video_id, resolved.ext, resolved.acodec, elapsed_ms, extras_str,
    )
    return resolved
