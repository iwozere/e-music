"""
Import fully downloaded YouTube tracks into MUSIC_PATH (Artist/Album/track.mp3),
with album.png, ID3 tags, and album_meta.json (who saved which track_id).

Artist and album folders are resolved case-insensitively so case-sensitive hosts
(e.g. Linux on Raspberry Pi) do not split the same act across ``Smokie`` vs ``SMOKIE``.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from mutagen.id3 import APIC, ID3, TALB, TIT2, TPE1  # pyright: ignore[reportPrivateImportUsage]
from mutagen.mp3 import MP3
from sqlmodel import Session, col, select

from app.config import settings
from app.db import engine
from app.models import Track
from app.services.ytmusic import yt
from app.utils.logger import setup_logger

_logger = setup_logger(__name__)

_META_VERSION = 1
_ALBUM_LOCKS: Dict[str, threading.Lock] = {}
_ALBUM_LOCKS_GUARD = threading.Lock()
_REMOTE_IMPORT_LOCKS: Dict[str, threading.Lock] = {}
_REMOTE_IMPORT_GUARD = threading.Lock()

_WIN_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def _lock_for_remote(remote_id: str) -> threading.Lock:
    with _REMOTE_IMPORT_GUARD:
        if remote_id not in _REMOTE_IMPORT_LOCKS:
            _REMOTE_IMPORT_LOCKS[remote_id] = threading.Lock()
        return _REMOTE_IMPORT_LOCKS[remote_id]


def _lock_for_album_dir(album_dir: str) -> threading.Lock:
    with _ALBUM_LOCKS_GUARD:
        if album_dir not in _ALBUM_LOCKS:
            _ALBUM_LOCKS[album_dir] = threading.Lock()
        return _ALBUM_LOCKS[album_dir]


def sanitize_segment(name: Optional[str], max_len: int = 80) -> str:
    if not name or not str(name).strip():
        return "Unknown"
    s = str(name).strip()
    for c in '<>:"/\\|?*':
        s = s.replace(c, "_")
    s = re.sub(r"[\x00-\x1f]", "_", s)
    s = s.rstrip(". ")
    key = s.upper()
    if key in _WIN_RESERVED:
        s = f"_{s}"
    s = s[:max_len].rstrip(". ") or "Unknown"
    return s


def _resolve_library_subdir(parent: Path, segment: str) -> Path:
    """
    Pick a child directory under ``parent`` that matches ``segment`` case-insensitively,
    or ``parent / segment`` if none exists. Linux (e.g. Raspberry Pi ext4) treats
    ``Smokie`` and ``SMOKIE`` as different paths; this reuses the folder that is
    already on disk so imports stay under one artist/album tree.
    """
    if not segment:
        segment = "Unknown"
    key = segment.casefold()
    try:
        if parent.is_dir():
            for child in parent.iterdir():
                if child.is_dir() and child.name.casefold() == key:
                    if child.name != segment:
                        _logger.info(
                            "Library path: using existing %s (matched sanitized %r)",
                            child,
                            segment,
                        )
                    return child
    except OSError:
        _logger.warning(
            "Could not scan %s for case-insensitive directory match",
            parent,
            exc_info=True,
        )
    return parent / segment


def is_under_music_path(file_path: str) -> bool:
    try:
        fp = os.path.abspath(file_path)
        root = os.path.abspath(settings.MUSIC_PATH)
        return fp == root or fp.startswith(root + os.sep)
    except (OSError, ValueError):
        return False


def _rel_to_music(dest_file: Path) -> str:
    root = Path(settings.MUSIC_PATH).resolve()
    try:
        return dest_file.resolve().relative_to(root).as_posix()
    except ValueError:
        return dest_file.name


def _fetch_thumbnail_url(remote_id: str) -> Optional[str]:
    try:
        yt_info = yt.get_song(remote_id)
        if yt_info and "videoDetails" in yt_info:
            details = yt_info["videoDetails"]
            thumbs = details.get("thumbnail", {}).get("thumbnails", [])
            if thumbs:
                return str(thumbs[-1].get("url"))
    except Exception:
        _logger.warning("Could not fetch thumbnail URL for %s", remote_id)
    return None


def _ensure_album_art(album_dir: Path, remote_id: str, thumb_url: Optional[str]) -> None:
    png_path = album_dir / "album.png"
    if png_path.exists() and png_path.stat().st_size > 1000:
        return
    url = thumb_url or _fetch_thumbnail_url(remote_id)
    if not url:
        return
    try:
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            r = client.get(url)
            r.raise_for_status()
            png_path.write_bytes(r.content)
            _logger.info("Saved album art: %s", png_path)
    except Exception:
        _logger.exception("Failed to download album art for %s", remote_id)


def _append_album_meta(
    album_dir: Path,
    entry: Dict[str, Any],
) -> None:
    meta_path = album_dir / "album_meta.json"
    lock = _lock_for_album_dir(str(album_dir.resolve()))
    with lock:
        data: Dict[str, Any] = {"version": _META_VERSION, "entries": []}
        if meta_path.exists():
            try:
                raw = json.loads(meta_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict) and isinstance(raw.get("entries"), list):
                    data = raw
                    data.setdefault("version", _META_VERSION)
            except (json.JSONDecodeError, OSError):
                _logger.warning("Replacing corrupt album_meta.json at %s", meta_path)

        entries: List[Dict[str, Any]] = list(data["entries"])
        tid = entry.get("track_id")
        uid = entry.get("saved_by_user_id")
        if tid and uid and any(
            e.get("track_id") == tid and e.get("saved_by_user_id") == uid for e in entries
        ):
            return
        entries.append(entry)
        data["entries"] = entries
        tmp = meta_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(meta_path)


def _write_id3(dest: Path, title: str, artist: str, album: str, album_png: Optional[Path]) -> None:
    try:
        audio = MP3(dest, ID3=ID3)
        if audio.tags is None:
            audio.add_tags()
        if audio.tags is None:
            return
        audio.tags.setall("TIT2", [TIT2(encoding=3, text=title)])
        audio.tags.setall("TPE1", [TPE1(encoding=3, text=artist)])
        audio.tags.setall("TALB", [TALB(encoding=3, text=album)])
        if album_png and album_png.exists():
            try:
                pic = album_png.read_bytes()
                try:
                    audio.tags.delall("APIC")
                except KeyError:
                    pass
                audio.tags.add(
                    APIC(
                        encoding=3,
                        mime="image/png",
                        type=3,
                        desc="Cover",
                        data=pic,
                    )
                )
            except Exception:
                _logger.debug("Could not embed APIC for %s", dest, exc_info=True)
        audio.save(dest, v2_version=3)
    except Exception:
        _logger.exception("ID3 tagging failed for %s", dest)


def try_import_youtube_to_library(
    *,
    user_id: str,
    remote_id: str,
    source_mp3_path: str,
) -> None:
    """
    Move a downloaded YouTube mp3 into MUSIC_PATH and update DB + album_meta.json.
    Idempotent if track is already stored under MUSIC_PATH.
    """
    if not user_id or not remote_id or not source_mp3_path:
        return

    # The library layout + ID3 tagging path is MP3-only (mutagen.mp3). The streamer's
    # passthrough pipeline may now produce .webm/.aac artifacts; skip library import for
    # those — the cache still serves them, they just don't land in the Artist/Album tree.
    ext = os.path.splitext(source_mp3_path)[1].lower()
    if ext != ".mp3":
        _logger.debug(
            "library_import: skipping non-mp3 source for %s (ext=%s)", remote_id, ext
        )
        return

    with _lock_for_remote(remote_id):
        _try_import_youtube_to_library_impl(
            user_id=user_id,
            remote_id=remote_id,
            source_mp3_path=source_mp3_path,
        )


def _try_import_youtube_to_library_impl(
    *,
    user_id: str,
    remote_id: str,
    source_mp3_path: str,
) -> None:
    try:
        with Session(engine) as session:
            track = session.exec(select(Track).where(col(Track.remote_id) == remote_id)).first()
            if not track or track.source_type != "youtube":
                return

            if track.local_path and is_under_music_path(track.local_path):
                _logger.debug("Track %s already in music library path", remote_id)
                return

            candidate = os.path.abspath(source_mp3_path)
            if track.local_path and os.path.isfile(track.local_path):
                candidate = os.path.abspath(track.local_path)
            if not os.path.isfile(candidate):
                _logger.debug("Library import skipped: no file at %s", candidate)
                return

            artist = track.artist or "Unknown Artist"
            album = track.album or "Unknown Album"
            title = track.title or "Unknown Title"

            lib_root = Path(settings.MUSIC_PATH)
            lib_root.mkdir(parents=True, exist_ok=True)
            artist_seg = sanitize_segment(artist)
            album_seg = sanitize_segment(album)
            artist_dir = _resolve_library_subdir(lib_root, artist_seg)
            album_dir = _resolve_library_subdir(artist_dir, album_seg)
            album_dir.mkdir(parents=True, exist_ok=True)

            base_name = sanitize_segment(title)
            dest = album_dir / f"{base_name}.mp3"
            n = 2
            while dest.exists():
                dest = album_dir / f"{base_name} ({n}).mp3"
                n += 1

            _logger.info("Importing YouTube track %s to library: %s", remote_id, dest)
            shutil.move(candidate, dest)

            png_path = album_dir / "album.png"
            _ensure_album_art(album_dir, remote_id, track.thumbnail)
            _write_id3(dest, title, artist, album, png_path if png_path.exists() else None)

            saved_iso = datetime.now(timezone.utc).isoformat()
            _append_album_meta(
                album_dir,
                {
                    "track_id": track.id,
                    "remote_id": remote_id,
                    "saved_by_user_id": user_id,
                    "saved_at": saved_iso,
                    "library_rel_path": _rel_to_music(dest),
                },
            )

            track.local_path = str(dest.resolve())
            track.is_cached = True
            session.add(track)
            session.commit()
            _logger.info("Library import complete for track id=%s user=%s", track.id, user_id)
    except Exception:
        _logger.exception("Library import failed for remote_id=%s", remote_id)


def schedule_import_cached_file(user_id: str, remote_id: Optional[str], source_path: str) -> None:
    """BackgroundTasks entry: import when serving an existing temp/cache file to a logged-in user."""
    if not remote_id:
        return
    if is_under_music_path(source_path):
        return
    try_import_youtube_to_library(
        user_id=user_id,
        remote_id=remote_id,
        source_mp3_path=source_path,
    )
