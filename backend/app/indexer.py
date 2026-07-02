import re
import uuid
from pathlib import Path
from typing import Optional

from mutagen.id3 import ID3
from mutagen.mp3 import MP3
from sqlmodel import Session, select

from app.config import settings
from app.db import engine
from app.models import SourceType, Track
from app.utils.logger import setup_logger

_logger = setup_logger(__name__)


def _skip_transient_storage_path(file_path: Path) -> bool:
    """
    True if the file lives under disk cache or temp download dirs.

    Those folders hold transcoded YouTube files; indexing them produces junk rows
    (artist = folder name ``temp_cache``, title = video id).
    """
    roots: list[Path] = []
    for raw in (settings.CACHE_DIR, settings.TEMP_DIR):
        p = Path(raw)
        try:
            roots.append(p.resolve(strict=False))
        except OSError:
            roots.append(p)
    try:
        f = file_path.resolve(strict=False)
    except OSError:
        f = file_path
    for root in roots:
        try:
            if f == root or f.is_relative_to(root):
                return True
        except ValueError:
            continue
    return False

_CYRILLIC = re.compile(r"[а-яА-ЯёЁ]")


def _tag_text_garbled(val: Optional[str]) -> bool:
    """
    True if metadata should be discarded in favor of folder / re-decode heuristics.
    Catches ID3 decode failures (U+FFFD), all-placeholder artist strings, etc.
    """
    if val is None:
        return True
    s = str(val).strip()
    if not s:
        return True
    if "\ufffd" in s:
        return True
    letters = [c for c in s if c.isalpha()]
    if letters and all(c == "?" for c in letters):
        return True
    if len(s) >= 4 and s.count("?") >= len(s) * 0.5:
        return True
    return False


def _decode_id3_text(val: str) -> str:
    """
    Recover Cyrillic (and similar) when mutagen gave Latin-1-style mojibake.
    Tries CP1251 and UTF-8 bytes-via-latin-1, same family of fixes as common tag editors.
    """
    if not val or "\ufffd" in val:
        return val
    candidates = [val]
    if all(ord(c) < 256 for c in val):
        for encoding in ("cp1251", "utf-8"):
            try:
                fixed = val.encode("latin-1").decode(encoding)
                candidates.append(fixed)
            except (UnicodeEncodeError, UnicodeDecodeError):
                pass
    for c in candidates:
        if _CYRILLIC.search(c) and "\ufffd" not in c:
            return c
    return val


def scan_file(file_path: Path, session: Session) -> None:
    """
    Scan a single MP3 file for metadata and index it into the database.

    Args:
        file_path: Absolute path to the MP3 file.
        session: Active database session.
    """
    try:
        if not file_path.suffix.lower() == ".mp3":
            return

        if _skip_transient_storage_path(file_path):
            return

        # Check if file already indexed
        statement = select(Track).where(Track.local_path == str(file_path))
        existing = session.exec(statement).first()
        
        # If already indexed and title, artist, AND album look valid, skip
        if existing:
            title_ok = not _tag_text_garbled(str(existing.title))
            artist_ok = existing.artist is not None and not _tag_text_garbled(
                str(existing.artist)
            )
            album_ok = existing.album is not None and not _tag_text_garbled(
                str(existing.album)
            )
            if title_ok and artist_ok and album_ok:
                return

        audio = MP3(file_path, ID3=ID3)

        def clean_tag(tag_list):
            if not tag_list:
                return None
            val = str(tag_list[0])
            return _decode_id3_text(val)

        title = clean_tag(audio.get("TIT2")) or file_path.stem
        artist = clean_tag(audio.get("TPE1")) or clean_tag(audio.get("TPE2"))
        album = clean_tag(audio.get("TALB"))

        if _tag_text_garbled(artist):
            artist = None
        if _tag_text_garbled(album):
            album = None
        duration = int(audio.info.length) if audio.info else None

        # Hierarchical Folder Fallbacks
        parent = file_path.parent
        grandparent = parent.parent
        
        # Fallback for Album if missing or garbage
        if not album or _tag_text_garbled(str(album)):
            if parent.name.lower() not in ["library", "e-music", "music"]:
                album = parent.name
            else:
                album = "Unknown Album"

        # Fallback for Artist if missing or garbage
        if not artist or _tag_text_garbled(str(artist)):
            if grandparent.name.lower() not in ["library", "e-music", "music"]:
                # Structure: .../Artist/Album/Track.mp3
                artist = grandparent.name
            elif parent.name.lower() not in ["library", "e-music", "music"]:
                # Structure: .../Artist/Track.mp3
                artist = parent.name
            else:
                artist = "Unknown Artist"

        # Sanity check for title (prefer Unicode filename when tags are junk)
        if title and _tag_text_garbled(str(title)):
            title = file_path.stem

        if existing:
            existing.title = str(title)
            existing.artist = str(artist) if artist else None
            existing.album = str(album) if album else None
            existing.duration = duration
            session.add(existing)
            _logger.info("Updated track: %s - %s", artist, title)
        else:
            track = Track(
                id=str(uuid.uuid4()),
                title=str(title),
                artist=str(artist) if artist else None,
                album=str(album) if album else None,
                source_type=SourceType.local,
                local_path=str(file_path),
                is_cached=True,
                duration=duration
            )
            session.add(track)
            _logger.info("Indexed new track: %s - %s", artist, title)
        
        session.commit()
    except Exception:
        _logger.exception("Error indexing file: %s", file_path)

def scan_library(library_path: str) -> None:
    """
    Recursively scan a directory for MP3 files and index them.

    Args:
        library_path: Path to the music library directory.
    """
    library_dir = Path(library_path)
    if not library_dir.exists():
        _logger.error("Library path does not exist: %s", library_path)
        return

    _logger.info("Starting library scan at %s", library_path)

    with Session(engine) as session:
        for file_path in library_dir.rglob("*.mp3"):
            if _skip_transient_storage_path(file_path):
                continue
            scan_file(file_path, session)
    _logger.info("Library scan complete")

def run_indexer() -> None:
    """
    Convenience function to run the indexer on the default library path.
    """
    from app.config import settings
    scan_library(settings.MUSIC_PATH)
