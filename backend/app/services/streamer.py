"""
Streaming service for MySpotify.

Uses subprocess.Popen (not asyncio.create_subprocess_exec) so it works on
both Windows SelectorEventLoop and Linux EpollEventLoop.
FastAPI automatically runs sync generators in a thread-pool executor.

Feature 1 (fast YouTube playback) introduces a resolver-based primary path:
    yt_resolver → httpx stream → ffmpeg (stream-copy by default) → HTTP response.
The legacy subprocess pipeline (yt-dlp -o - | ffmpeg transcode) stays as a
fallback when the resolver returns nothing or when ``STREAM_FORCE_LEGACY_SUBPROCESS``
is set. Both paths still write to the same temp-cache file for the LRU layer.
"""
import asyncio
import mimetypes
import os
import shlex
import sys
import shutil
import subprocess
import threading
import time
from typing import Dict, Generator, Iterator, Optional, Union

import httpx
from fastapi import HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from sqlmodel import Session, select

from app.models import Track
from app.db import engine
from app.config import settings
from app.utils.logger import setup_logger
from app.services import library_import
from app.services.yt_resolver import ResolvedFormat, invalidate as resolver_invalidate, resolve as resolver_resolve

_logger = setup_logger(__name__)

PERSISTENT_CACHE_DIR: str = settings.CACHE_DIR
TEMP_CACHE_DIR: str = settings.TEMP_DIR

# Registry to prevent duplicate downloads for the same track
_active_downloads: Dict[str, threading.Event] = {}
_active_downloads_lock = threading.Lock()

# Short-lived cache: recent "no audio from pipeline" per video id (avoids repeated work and
# gives fast JSON errors for follow-up requests, e.g. the player's fetch for a toast message).
_youtube_fail_lock = threading.Lock()
_youtube_stream_failures: Dict[str, tuple[float, str]] = {}
_FAIL_CACHE_SECS = 90.0

# Log a warning when a single ffmpeg-stdout read or a googlevideo chunk gap exceeds this.
_STALL_WARN_MS = 2000


def _youtube_fail_clear(video_id: str) -> None:
    with _youtube_fail_lock:
        _youtube_stream_failures.pop(video_id, None)


def _youtube_fail_peek(video_id: str) -> Optional[str]:
    now = time.monotonic()
    with _youtube_fail_lock:
        entry = _youtube_stream_failures.get(video_id)
        if not entry:
            return None
        until, msg = entry
        if now > until:
            _youtube_stream_failures.pop(video_id, None)
            return None
        return msg


def _youtube_fail_record(video_id: str, message: str) -> None:
    with _youtube_fail_lock:
        _youtube_stream_failures[video_id] = (
            time.monotonic() + _FAIL_CACHE_SECS,
            message,
        )


def _build_yt_dlp_argv(track_video_id: str) -> list[str]:
    """yt-dlp argv (legacy fallback path). Prefer clients that still work from server/datacenter IPs."""
    exe = _find_executable("yt-dlp")
    clients = (settings.YTDLP_YOUTUBE_PLAYER_CLIENT or "tv,web,mweb").strip()
    if not clients:
        clients = "tv,web,mweb"
    argv: list[str] = [
        exe,
        "--no-playlist",
        "-f",
        "ba/bestaudio/best/worst",
        "--extractor-args",
        f"youtube:player_client={clients}",
    ]
    ck = (settings.YTDLP_COOKIES_FILE or "").strip()
    if ck and os.path.isfile(ck):
        argv.extend(["--cookies", ck])
    extra = (settings.YTDLP_EXTRA_ARGS or "").strip()
    if extra:
        argv.extend(shlex.split(extra))
    argv.extend(["-o", "-", f"https://www.youtube.com/watch?v={track_video_id}"])
    return argv


def _common_ffmpeg_prefix() -> list[str]:
    ff = _ffmpeg_executable()
    argv: list[str] = [ff, "-hide_banner", "-loglevel", "error"]
    if settings.STREAM_LOW_LATENCY:
        argv += ["-fflags", "nobuffer", "-flags", "low_delay"]
    argv += [
        "-analyzeduration",
        str(int(settings.STREAM_ANALYZEDURATION_US)),
        "-probesize",
        str(int(settings.STREAM_PROBESIZE_BYTES)),
    ]
    return argv


def _build_ffmpeg_transcode_argv() -> list[str]:
    """MP3 transcode fallback (legacy behavior, matches what the codebase used before)."""
    kbps = max(64, int(settings.STREAM_TRANSCODE_BITRATE_KBPS))
    return _common_ffmpeg_prefix() + [
        "-i",
        "pipe:0",
        "-vn",
        "-f",
        "mp3",
        "-acodec",
        "libmp3lame",
        "-ab",
        f"{kbps}k",
        "pipe:1",
    ]


def _build_ffmpeg_passthrough_argv(container: str) -> list[str]:
    """
    Stream-copy pipe for browser-safe codecs.

    container="webm" → Opus inside WebM (Chrome/Firefox/Edge, recent Safari).
    container="adts" → raw AAC (Safari-safe, Chrome/Edge safe).
    """
    argv = _common_ffmpeg_prefix() + ["-i", "pipe:0", "-vn", "-c:a", "copy"]
    if container == "webm":
        argv += ["-f", "webm", "pipe:1"]
    elif container == "adts":
        argv += ["-f", "adts", "pipe:1"]
    elif container == "mp4":
        argv += [
            "-movflags",
            "+empty_moov+default_base_moof+frag_keyframe",
            "-f",
            "mp4",
            "pipe:1",
        ]
    else:
        raise ValueError(f"Unsupported passthrough container: {container}")
    return argv


# Browsers rely on Content-Type for <audio>; guess_type is incomplete on some platforms.
_AUDIO_EXT_MEDIA_TYPES: Dict[str, str] = {
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/opus",
    ".wav": "audio/wav",
    ".webm": "audio/webm",
    ".wma": "audio/x-ms-wma",
}


def _audio_media_type_for_path(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    if ext in _AUDIO_EXT_MEDIA_TYPES:
        return _AUDIO_EXT_MEDIA_TYPES[ext]
    guessed, _ = mimetypes.guess_type(file_path)
    if guessed and guessed.startswith("audio/"):
        return guessed
    return "application/octet-stream"


def _parse_total_length(response: "httpx.Response") -> Optional[int]:
    """Total resource size from a Range response.

    Prefers the ``/<total>`` suffix of ``Content-Range`` (set on 206 replies);
    falls back to ``Content-Length`` for a 200 (server ignored Range). Returns
    None when neither is parseable so the feeder loops until a short/empty chunk.
    """
    content_range = response.headers.get("Content-Range")
    if content_range and "/" in content_range:
        total_part = content_range.rsplit("/", 1)[-1].strip()
        if total_part.isdigit():
            return int(total_part)
    if response.status_code == 200:
        clen = response.headers.get("Content-Length")
        if clen and clen.isdigit():
            return int(clen)
    return None


def _find_executable(name: str) -> str:
    """Find an executable in PATH or the current venv's Scripts/bin directory."""
    found = shutil.which(name)
    if found:
        return found
    if sys.platform == "win32":
        venv_bin = os.path.join(os.path.dirname(sys.executable), f"{name}.exe")
    else:
        venv_bin = os.path.join(os.path.dirname(sys.executable), name)
    if os.path.exists(venv_bin):
        return venv_bin
    return name  # let the OS raise FileNotFoundError if missing


def _ffmpeg_executable() -> str:
    """Resolve the ffmpeg binary, honoring ``settings.FFMPEG_PATH`` (bundled build in standalone)."""
    override = (settings.FFMPEG_PATH or "").strip()
    if override:
        return override
    return _find_executable("ffmpeg")


def validate_cache_file(path: str, min_size: int = 100 * 1024) -> bool:
    """Check if a file exists and is reasonably large (e.g., > 100KB for a short audio clip)."""
    if not os.path.exists(path):
        return False
    size = os.path.getsize(path)
    if size < min_size:
        _logger.warning("Cache file %s is suspiciously small (%d bytes). Deleting.", path, size)
        try:
            os.remove(path)
        except Exception:
            pass
        return False
    return True


# ---------------------------------------------------------------------------
# Container / media-type helpers
# ---------------------------------------------------------------------------


def _cache_ext_and_media_type(resolved: Optional[ResolvedFormat]) -> tuple[str, str, str]:
    """
    Decide (cache_extension, media_type, ffmpeg_container) for a given resolved format.

    Returns legacy MP3 triplet when ``resolved`` is None (subprocess fallback path)
    or when passthrough is disabled / codec is not browser-safe.
    """
    if not settings.STREAM_PASSTHROUGH or resolved is None or not resolved.browser_safe_codec:
        return ".mp3", "audio/mpeg", "mp3"

    if resolved.is_aac:
        # ADTS is the most compatible AAC container for a live pipe (Safari + Chrome + FF).
        return ".aac", "audio/aac", "adts"
    # Opus → WebM container.
    return ".webm", "audio/webm", "webm"


def _cached_artifact_paths(track_id: str) -> list[tuple[str, str, str]]:
    """
    Return (path, media_type, label) triples for any on-disk artifact that matches this id.

    We prefer persistent cache over temp cache; within each directory we look at both the
    legacy ``.mp3`` and the new native-container extensions (``.webm``/``.aac``/``.m4a``).
    """
    candidates: list[tuple[str, str, str]] = []
    for directory, label in (
        (PERSISTENT_CACHE_DIR, "persistent"),
        (TEMP_CACHE_DIR, "temp"),
    ):
        for ext in (".mp3", ".webm", ".aac", ".m4a"):
            path = os.path.join(directory, f"{track_id}{ext}")
            candidates.append((path, _AUDIO_EXT_MEDIA_TYPES.get(ext, "application/octet-stream"), label))
    return candidates


# ---------------------------------------------------------------------------
# Shared stdout → HTTP + disk helper
# ---------------------------------------------------------------------------


def _yield_from_ffmpeg_stdout(
    ff_out,  # IO[bytes]
    *,
    download_path: str,
    track_id: str,
    path_label: str,
    t_start: float,
) -> Generator[bytes, None, None]:
    """Write ffmpeg stdout to disk while yielding chunks to the HTTP client.

    Applies the configurable pre-buffer and emits first-byte / stall-warn log events.
    bytes_so_far tracks the running total for stall-warn context only.
    """
    prebuf_target = settings.STREAM_PREBUFFER_BYTES
    prebuf: Optional[bytearray] = bytearray() if prebuf_target > 0 else None
    t_last_chunk = time.monotonic()
    bytes_so_far = 0
    first_byte_ms: Optional[int] = None

    with open(download_path, "wb") as cache_file:
        while True:
            chunk: bytes = ff_out.read(64 * 1024)
            t_got = time.monotonic()
            if not chunk:
                break

            wait_ms = int((t_got - t_last_chunk) * 1000)
            if wait_ms >= _STALL_WARN_MS:
                _logger.warning(
                    "streamer: stdout stall path=%s track=%s stall_ms=%d bytes_yielded=%d",
                    path_label, track_id, wait_ms, bytes_so_far,
                )
            t_last_chunk = t_got

            cache_file.write(chunk)

            if prebuf is not None:
                prebuf.extend(chunk)
                if len(prebuf) < prebuf_target:
                    continue
                chunk = bytes(prebuf)
                prebuf = None

            if first_byte_ms is None:
                first_byte_ms = int((t_got - t_start) * 1000)
                _logger.info(
                    "streamer: first byte path=%s track=%s elapsed_ms=%d bytes=%d",
                    path_label, track_id, first_byte_ms, len(chunk),
                )
            yield chunk
            bytes_so_far += len(chunk)

        if prebuf and len(prebuf) > 0:
            to_send = bytes(prebuf)
            if first_byte_ms is None:
                first_byte_ms = int((time.monotonic() - t_start) * 1000)
                _logger.info(
                    "streamer: first byte path=%s track=%s elapsed_ms=%d bytes=%d",
                    path_label, track_id, first_byte_ms, len(to_send),
                )
            yield to_send


# ---------------------------------------------------------------------------
# Primary path: resolver → httpx → ffmpeg
# ---------------------------------------------------------------------------


def _stream_resolved(
    *,
    track_id: str,
    resolved: ResolvedFormat,
    download_path: str,
    final_path: str,
    done_event: threading.Event,
    library_user_id: Optional[str],
) -> Generator[bytes, None, None]:
    """
    Pull bytes from googlevideo with httpx, pipe them into ffmpeg (stream-copy by default),
    and yield the re-muxed bytes back to the HTTP client while also writing them to disk.

    Any exception aborts the pipeline, kills child processes, removes the partial file,
    and signals ``done_event`` so waiting threads don't block forever.
    """
    success = False
    bytes_yielded = 0
    ff_proc: Optional[subprocess.Popen] = None
    feeder_err: list[str] = []

    t_start = time.monotonic()

    _, _, container = _cache_ext_and_media_type(resolved)
    if container == "mp3":
        ffmpeg_cmd = _build_ffmpeg_transcode_argv()
        path_label = "resolver+transcode"
    else:
        ffmpeg_cmd = _build_ffmpeg_passthrough_argv(container)
        path_label = f"resolver+copy:{container}"

    popen_kwargs: dict = {}
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    try:
        ff_proc = subprocess.Popen(
            ffmpeg_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **popen_kwargs,
        )
    except Exception:
        _logger.exception("streamer: failed to start ffmpeg for %s", track_id)
        done_event.set()
        with _active_downloads_lock:
            _active_downloads.pop(track_id, None)
        return

    assert ff_proc.stdin is not None and ff_proc.stdout is not None

    def _feed_from_http() -> None:
        """Worker thread: pump bytes from googlevideo into ffmpeg.stdin.

        Pulls the resolved URL in sequential HTTP Range chunks rather than one long
        GET. Google throttles a single non-ranged full-file pull to ~playback rate
        (the cause of mid-track stalls on non-cached tracks); a fresh ranged request
        per chunk resets the per-connection throttle window so aggregate throughput
        stays well above playback rate. Falls back to a single GET when the server
        ignores Range (status 200) or chunking is disabled via config.
        """
        base_headers = dict(resolved.http_headers or {})
        chunk_bytes = int(settings.STREAM_HTTP_CHUNK_BYTES)
        # Some resolved googlevideo URLs already pin a byte window via a ``range=``
        # query param; layering our own Range header on top yields 416s. In that case
        # (and when chunking is disabled) fall back to a single streaming GET.
        url_has_range = "range=" in (resolved.url or "").lower()
        use_chunking = chunk_bytes > 0 and not url_has_range
        timeout = httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=30.0)
        # Shared across chunks so a stall between two range requests is still caught.
        state = {"t_last": time.monotonic(), "bytes_fed": 0}

        def _pump(response: "httpx.Response") -> bool:
            """Stream one response body into ffmpeg. Returns False to abort the feeder."""
            for chunk in response.iter_bytes(64 * 1024):
                if not chunk:
                    continue
                now = time.monotonic()
                gap_ms = int((now - state["t_last"]) * 1000)
                if gap_ms >= _STALL_WARN_MS:
                    _logger.warning(
                        "streamer: feeder stall track=%s gap_ms=%d bytes_fed=%d",
                        track_id, gap_ms, state["bytes_fed"],
                    )
                state["t_last"] = now
                state["bytes_fed"] += len(chunk)
                try:
                    ff_proc.stdin.write(chunk)
                except (BrokenPipeError, ValueError):
                    # ffmpeg exited or client disconnected.
                    return False
            return True

        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                if not use_chunking:
                    # Single streaming GET (chunking disabled or URL self-ranges).
                    with client.stream("GET", resolved.url, headers=base_headers) as response:
                        if response.status_code in (403, 410):
                            resolver_invalidate(resolved.video_id)
                            feeder_err.append(f"upstream {response.status_code}")
                            return
                        if response.status_code >= 400:
                            feeder_err.append(f"upstream {response.status_code}")
                            return
                        _pump(response)
                    return

                pos = 0
                total: Optional[int] = None
                while True:
                    req_headers = dict(base_headers)
                    req_headers["Range"] = f"bytes={pos}-{pos + chunk_bytes - 1}"
                    with client.stream("GET", resolved.url, headers=req_headers) as response:
                        if response.status_code in (403, 410):
                            resolver_invalidate(resolved.video_id)
                            feeder_err.append(f"upstream {response.status_code}")
                            return
                        # 416 = we asked past EOF. If we already have data this is a
                        # clean end-of-stream, not an error (don't poison caching).
                        if response.status_code == 416:
                            if state["bytes_fed"] == 0:
                                feeder_err.append("upstream 416 on first range")
                            break
                        if response.status_code not in (200, 206):
                            feeder_err.append(f"upstream {response.status_code}")
                            return
                        if total is None:
                            total = _parse_total_length(response)
                        before = state["bytes_fed"]
                        if not _pump(response):
                            return
                        got = state["bytes_fed"] - before
                    # Server ignored Range and sent the whole body — we're done.
                    if response.status_code == 200:
                        break
                    # Short read (< requested window) means we reached EOF.
                    if got < chunk_bytes:
                        break
                    pos += got
                    if total is not None and pos >= total:
                        break
        except httpx.HTTPError as exc:
            feeder_err.append(str(exc))
        except Exception as exc:  # pylint: disable=broad-exception-caught
            feeder_err.append(repr(exc))
        finally:
            try:
                ff_proc.stdin.close()
            except Exception:
                pass

    feeder = threading.Thread(target=_feed_from_http, name=f"yt-feed-{track_id}", daemon=True)
    feeder.start()

    try:
        for chunk in _yield_from_ffmpeg_stdout(
            ff_proc.stdout,
            download_path=download_path,
            track_id=track_id,
            path_label=path_label,
            t_start=t_start,
        ):
            yield chunk
            bytes_yielded += len(chunk)

        ff_proc.wait()
        feeder.join(timeout=5)

        ff_ok = ff_proc.returncode == 0
        if not ff_ok:
            err = (ff_proc.stderr.read() if ff_proc.stderr else b"").decode(errors="replace").strip()
            _logger.error("streamer: ffmpeg exit=%d track=%s err=%s", ff_proc.returncode, track_id, err)

        if feeder_err:
            _logger.warning("streamer: feeder errors for %s: %s", track_id, "; ".join(feeder_err))

        if bytes_yielded > 0 and os.path.exists(download_path) and ff_ok and not feeder_err:
            if os.path.exists(final_path):
                os.remove(final_path)
            os.rename(download_path, final_path)
            success = True
            total_ms = int((time.monotonic() - t_start) * 1000)
            _logger.info(
                "streamer: cached track=%s path=%s bytes=%d total_ms=%d",
                track_id,
                path_label,
                bytes_yielded,
                total_ms,
            )
    except Exception:
        _logger.exception("streamer: resolved pipeline error for %s", track_id)
    finally:
        if ff_proc and ff_proc.poll() is None:
            try:
                ff_proc.kill()
            except Exception:
                pass
        if not success and os.path.exists(download_path):
            try:
                os.remove(download_path)
            except Exception:
                pass
        done_event.set()
        with _active_downloads_lock:
            _active_downloads.pop(track_id, None)

        if success:
            _update_track_after_cache(track_id, final_path, library_user_id)


# ---------------------------------------------------------------------------
# Legacy subprocess path (safety net)
# ---------------------------------------------------------------------------


def _stream_legacy_subprocess(
    *,
    track_id: str,
    download_path: str,
    final_path: str,
    done_event: threading.Event,
    library_user_id: Optional[str],
) -> Generator[bytes, None, None]:
    """yt-dlp -o - | ffmpeg transcode → HTTP (the original implementation)."""
    success = False
    bytes_yielded = 0
    yt_proc: Optional[subprocess.Popen] = None
    ff_proc: Optional[subprocess.Popen] = None
    t_start = time.monotonic()

    yt_cmd = _build_yt_dlp_argv(track_id)
    ffmpeg_cmd = _build_ffmpeg_transcode_argv()

    popen_kwargs: dict = {}
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    try:
        yt_proc = subprocess.Popen(
            yt_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **popen_kwargs
        )
        ff_proc = subprocess.Popen(
            ffmpeg_cmd,
            stdin=yt_proc.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **popen_kwargs,
        )
        if yt_proc.stdout:
            yt_proc.stdout.close()

        ff_out = ff_proc.stdout
        if ff_out is None:
            _logger.error("streamer: legacy ffmpeg stdout missing for %s", track_id)
            return

        for chunk in _yield_from_ffmpeg_stdout(
            ff_out,
            download_path=download_path,
            track_id=track_id,
            path_label="legacy-subprocess",
            t_start=t_start,
        ):
            yield chunk
            bytes_yielded += len(chunk)

        yt_proc.wait()
        ff_proc.wait()

        if yt_proc.returncode != 0:
            err = (yt_proc.stderr.read() if yt_proc.stderr else b"").decode(errors="replace").strip()
            _logger.error("streamer: yt-dlp exit=%d err=%s", yt_proc.returncode, err)
            return
        if ff_proc.returncode != 0:
            err = (ff_proc.stderr.read() if ff_proc.stderr else b"").decode(errors="replace").strip()
            _logger.error("streamer: ffmpeg exit=%d err=%s", ff_proc.returncode, err)
            return

        if bytes_yielded > 0 and os.path.exists(download_path):
            if os.path.exists(final_path):
                os.remove(final_path)
            os.rename(download_path, final_path)
            success = True
            total_ms = int((time.monotonic() - t_start) * 1000)
            _logger.info(
                "streamer: cached track=%s path=legacy-subprocess bytes=%d total_ms=%d",
                track_id,
                bytes_yielded,
                total_ms,
            )
    except Exception:
        _logger.exception("streamer: legacy pipeline error for %s", track_id)
    finally:
        for proc in (ff_proc, yt_proc):
            if proc and proc.poll() is None:
                try:
                    proc.kill()
                except Exception:
                    pass
        if not success and os.path.exists(download_path):
            try:
                os.remove(download_path)
            except Exception:
                pass
        done_event.set()
        with _active_downloads_lock:
            _active_downloads.pop(track_id, None)

        if success:
            _update_track_after_cache(track_id, final_path, library_user_id)


def _update_track_after_cache(track_id: str, final_path: str, library_user_id: Optional[str]) -> None:
    """Persist cache info + optionally import into library. Safe to call from worker threads."""
    try:
        with Session(engine) as session:
            track = session.exec(select(Track).where(Track.remote_id == track_id)).first()
            if track:
                track.is_cached = True
                track.local_path = final_path
                session.add(track)
                session.commit()
    except Exception:
        _logger.exception("streamer: failed to update DB for %s", track_id)
    if library_user_id:
        try:
            library_import.try_import_youtube_to_library(
                user_id=library_user_id,
                remote_id=track_id,
                source_mp3_path=final_path,
            )
        except Exception:
            _logger.exception("streamer: library import failed for %s", track_id)


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


async def stream_youtube(
    track_id: str,
    *,
    allow_disk_cache: bool = True,
    library_user_id: Optional[str] = None,
) -> Union[StreamingResponse, FileResponse]:
    """
    Stream audio from YouTube. Primary path: yt_resolver → httpx → ffmpeg (stream-copy).
    Falls back to the legacy yt-dlp subprocess pipeline when the resolver is unavailable
    or when ``STREAM_FORCE_LEGACY_SUBPROCESS`` is set.

    If allow_disk_cache is False, skip on-disk shortcuts so we do not serve stale/partial
    files when the DB says the track is not cached (those otherwise trigger HTTP 416 on
    Range requests from <audio>).
    """
    # 1. Serve from any healthy on-disk artifact (persistent > temp; native container > .mp3).
    if allow_disk_cache:
        for candidate_path, media_type, label in _cached_artifact_paths(track_id):
            if validate_cache_file(candidate_path):
                _logger.info("streamer: serving %s cache track=%s path=%s", label, track_id, candidate_path)
                _youtube_fail_clear(track_id)
                return FileResponse(candidate_path, media_type=media_type)

    # 2. If another request is already downloading this id, wait and try the cache again.
    with _active_downloads_lock:
        existing_event = _active_downloads.get(track_id)
    if existing_event is not None:
        _logger.info("streamer: download in progress for %s — waiting", track_id)
        existing_event.wait(timeout=60)
        for candidate_path, media_type, label in _cached_artifact_paths(track_id):
            if validate_cache_file(candidate_path):
                _youtube_fail_clear(track_id)
                return FileResponse(candidate_path, media_type=media_type)
        # Waiter failed; fall through and try ourselves.

    # 3. Cached failure short-circuit.
    cached_fail = _youtube_fail_peek(track_id)
    if cached_fail is not None:
        raise HTTPException(status_code=503, detail=cached_fail)

    # 4. Pre-flight binary check (ffmpeg is always required; yt-dlp only for the legacy path).
    ffmpeg_exe = _ffmpeg_executable()
    if not shutil.which(ffmpeg_exe):
        _logger.error("streamer: ffmpeg not found at %s", ffmpeg_exe)
        raise HTTPException(status_code=503, detail="ffmpeg missing — install it and add to PATH")

    # 5. Try the resolver unless explicitly disabled.
    resolved: Optional[ResolvedFormat] = None
    if not settings.STREAM_FORCE_LEGACY_SUBPROCESS:
        resolved = await resolver_resolve(track_id)

    use_legacy = resolved is None
    if use_legacy:
        yt_exe = _find_executable("yt-dlp")
        if not shutil.which(yt_exe):
            detail = (
                "YouTube playback unavailable: resolver returned no format and yt-dlp is missing. "
                "Install/upgrade: pip install -U 'yt-dlp[default]'."
            )
            _logger.error("streamer: %s", detail)
            _youtube_fail_record(track_id, detail)
            raise HTTPException(status_code=503, detail=detail)

    # 6. Register a download slot and pick artifact paths.
    os.makedirs(PERSISTENT_CACHE_DIR, exist_ok=True)
    os.makedirs(TEMP_CACHE_DIR, exist_ok=True)

    cache_ext, media_type, _container = _cache_ext_and_media_type(resolved)
    final_path = os.path.join(TEMP_CACHE_DIR, f"{track_id}{cache_ext}")
    download_path = f"{final_path}.download"

    done_event = threading.Event()
    with _active_downloads_lock:
        _active_downloads[track_id] = done_event

    if use_legacy:
        _logger.info("streamer: starting legacy subprocess pipeline track=%s", track_id)
        gen: Iterator[bytes] = _stream_legacy_subprocess(
            track_id=track_id,
            download_path=download_path,
            final_path=final_path,
            done_event=done_event,
            library_user_id=library_user_id,
        )
    else:
        _logger.info(
            "streamer: starting resolver pipeline track=%s ext=%s acodec=%s",
            track_id,
            resolved.ext,
            resolved.acodec,
        )
        gen = _stream_resolved(
            track_id=track_id,
            resolved=resolved,
            download_path=download_path,
            final_path=final_path,
            done_event=done_event,
            library_user_id=library_user_id,
        )

    first_chunk, rest = await asyncio.to_thread(_pull_first_chunk, gen)
    if first_chunk is None or rest is None:
        if not use_legacy and shutil.which(_find_executable("yt-dlp")):
            # Resolver URL produced no data — most likely a cached googlevideo URL
            # returned 403 (expired). The resolver cache was already invalidated by
            # _feed_from_http. Fall back to the legacy subprocess which resolves fresh.
            _logger.warning(
                "streamer: resolver pipeline empty for %s — falling back to legacy subprocess",
                track_id,
            )
            use_legacy = True
            legacy_final = os.path.join(TEMP_CACHE_DIR, f"{track_id}.mp3")
            legacy_download = f"{legacy_final}.download"
            legacy_event = threading.Event()
            with _active_downloads_lock:
                _active_downloads[track_id] = legacy_event
            gen = _stream_legacy_subprocess(
                track_id=track_id,
                download_path=legacy_download,
                final_path=legacy_final,
                done_event=legacy_event,
                library_user_id=library_user_id,
            )
            first_chunk, rest = await asyncio.to_thread(_pull_first_chunk, gen)
            media_type = "audio/mpeg"

        if first_chunk is None or rest is None:
            # Both paths failed — short-circuit subsequent requests briefly.
            fail_detail = (
                "Could not start audio from YouTube (no data from yt-dlp/ffmpeg). "
                "Install/upgrade: pip install -U 'yt-dlp[default]' with Deno or Node 20+ in PATH "
                "(Docker image includes Deno). Set YTDLP_COOKIES_FILE if needed. "
                "See server logs for yt-dlp/ffmpeg stderr."
            )
            _youtube_fail_record(track_id, fail_detail)
            raise HTTPException(status_code=503, detail=fail_detail)

    _youtube_fail_clear(track_id)

    def _body() -> Generator[bytes, None, None]:
        yield first_chunk
        yield from rest

    return StreamingResponse(
        _body(),
        media_type=media_type,
        headers={
            "Accept-Ranges": "none",
            "Cache-Control": "no-store, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


def _pull_first_chunk(
    gen: Iterator[bytes],
) -> Union[tuple[bytes, Iterator[bytes]], tuple[None, None]]:
    """Run first step of the sync generator off the asyncio event loop."""
    try:
        chunk = next(gen)
    except StopIteration:
        return (None, None)
    return (chunk, gen)


def get_local_stream(file_path: str) -> FileResponse:
    """Stream a local audio file with HTTP Range support."""
    _logger.info("Streaming local file: %s", file_path)
    return FileResponse(file_path, media_type=_audio_media_type_for_path(file_path))


# ---------------------------------------------------------------------------
# Prefetch (Feature 2): warm the temp cache for the next track in the queue.
# ---------------------------------------------------------------------------


class PrefetchStatus:
    CACHED = "cached"  # Already on disk (temp or persistent), no work needed.
    IN_PROGRESS = "in_progress"  # Another request is already downloading this id.
    STARTED = "started"  # A new prefetch worker has been spawned.
    SKIPPED = "skipped"  # Feature disabled or concurrency cap hit.


_prefetch_sema_lock = threading.Lock()
_prefetch_semaphore: Optional[threading.BoundedSemaphore] = None


def _get_prefetch_semaphore() -> threading.BoundedSemaphore:
    """Lazily-created semaphore so tests/config changes take effect on first use."""
    global _prefetch_semaphore
    if _prefetch_semaphore is not None:
        return _prefetch_semaphore
    with _prefetch_sema_lock:
        if _prefetch_semaphore is None:
            cap = max(1, int(settings.PREFETCH_MAX_CONCURRENT))
            _prefetch_semaphore = threading.BoundedSemaphore(value=cap)
        return _prefetch_semaphore


def _drain_generator(gen: Iterator[bytes]) -> None:
    """Consume a stream generator to completion (discarding bytes).

    The underlying ``_stream_*`` generators already write to the temp cache as a
    side-effect; we just need to pull from them so the pipeline runs end-to-end.
    """
    try:
        for _ in gen:
            pass
    except Exception:  # pylint: disable=broad-exception-caught
        _logger.exception("streamer: prefetch drain raised unexpectedly")


async def prefetch_youtube(
    track_id: str,
    *,
    library_user_id: Optional[str] = None,
) -> str:
    """Kick off (or join) a background warm-up download for ``track_id``.

    Returns a ``PrefetchStatus`` string. Safe to call repeatedly; dedup is handled
    via the shared ``_active_downloads`` registry and an in-process semaphore.
    """
    if not settings.PREFETCH_ENABLED:
        return PrefetchStatus.SKIPPED

    # 1. Already cached? No-op.
    for candidate_path, _media_type, _label in _cached_artifact_paths(track_id):
        if validate_cache_file(candidate_path):
            return PrefetchStatus.CACHED

    # 2. Another request is already downloading → join (no new worker).
    with _active_downloads_lock:
        if track_id in _active_downloads:
            return PrefetchStatus.IN_PROGRESS

    # 3. Concurrency cap. Non-blocking: if the budget is used up, decline gracefully.
    sema = _get_prefetch_semaphore()
    if not sema.acquire(blocking=False):
        _logger.info("streamer: prefetch skipped (concurrency cap) track=%s", track_id)
        return PrefetchStatus.SKIPPED

    # 4. Pre-flight: ffmpeg required for both pipelines.
    ffmpeg_exe = _ffmpeg_executable()
    if not shutil.which(ffmpeg_exe):
        sema.release()
        _logger.warning("streamer: prefetch skipped (ffmpeg missing) track=%s", track_id)
        return PrefetchStatus.SKIPPED

    # 5. Resolve (same rules as the live play path).
    resolved: Optional[ResolvedFormat] = None
    if not settings.STREAM_FORCE_LEGACY_SUBPROCESS:
        resolved = await resolver_resolve(track_id)

    use_legacy = resolved is None
    if use_legacy and not shutil.which(_find_executable("yt-dlp")):
        sema.release()
        _logger.info("streamer: prefetch skipped (no resolver + no yt-dlp) track=%s", track_id)
        return PrefetchStatus.SKIPPED

    os.makedirs(PERSISTENT_CACHE_DIR, exist_ok=True)
    os.makedirs(TEMP_CACHE_DIR, exist_ok=True)

    cache_ext, _media_type, _container = _cache_ext_and_media_type(resolved)
    final_path = os.path.join(TEMP_CACHE_DIR, f"{track_id}{cache_ext}")
    download_path = f"{final_path}.download"

    # 6. Register the download slot under lock so a concurrent play doesn't double-start.
    done_event = threading.Event()
    with _active_downloads_lock:
        if track_id in _active_downloads:
            sema.release()
            return PrefetchStatus.IN_PROGRESS
        _active_downloads[track_id] = done_event

    if use_legacy:
        _logger.info("streamer: prefetch starting (legacy) track=%s", track_id)
        gen: Iterator[bytes] = _stream_legacy_subprocess(
            track_id=track_id,
            download_path=download_path,
            final_path=final_path,
            done_event=done_event,
            library_user_id=library_user_id,
        )
    else:
        _logger.info(
            "streamer: prefetch starting (resolver) track=%s ext=%s acodec=%s",
            track_id,
            resolved.ext,
            resolved.acodec,
        )
        gen = _stream_resolved(
            track_id=track_id,
            resolved=resolved,
            download_path=download_path,
            final_path=final_path,
            done_event=done_event,
            library_user_id=library_user_id,
        )

    def _worker() -> None:
        try:
            _drain_generator(gen)
        finally:
            sema.release()

    threading.Thread(target=_worker, name=f"prefetch-{track_id}", daemon=True).start()
    return PrefetchStatus.STARTED
