import uuid
from pathlib import Path

from mutagen.mp3 import MP3
from mutagen.id3 import ID3
from sqlmodel import Session, select

from app.models import Track
from app.db import engine
from app.utils.logger import setup_logger

_logger = setup_logger(__name__)

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
            
        # Check if file already indexed
        statement = select(Track).where(Track.local_path == str(file_path))
        existing = session.exec(statement).first()
        
        # If already indexed and title, artist, AND album look valid, skip
        if existing:
            title_ok = not all(c == '?' or c == ' ' for c in str(existing.title))
            artist_ok = existing.artist is not None and not all(c == '?' or c == ' ' for c in str(existing.artist))
            album_ok = existing.album is not None and not all(c == '?' or c == ' ' for c in str(existing.album))
            if title_ok and artist_ok and album_ok:
                return

        audio = MP3(file_path, ID3=ID3)
        
        def clean_tag(tag_list):
            if not tag_list: return None
            val = str(tag_list[0])
            # Common fix for mangled CP1251 interpreted as Latin-1
            if all(ord(c) < 256 for c in val):
                try:
                    # Attempt to recover Cyrillic from mis-decoded bytes
                    test_val = val.encode('latin-1').decode('cp1251')
                    # If it looks like Cyrillic (contains at least one cyrillic char), use it
                    import re
                    if re.search(r'[а-яА-ЯёЁ]', test_val):
                        return test_val
                except (UnicodeEncodeError, UnicodeDecodeError):
                    pass
            return val

        title = clean_tag(audio.get("TIT2")) or file_path.stem
        artist = clean_tag(audio.get("TPE1")) or clean_tag(audio.get("TPE2"))
        album = clean_tag(audio.get("TALB"))
        duration = int(audio.info.length) if audio.info else None

        # Hierarchical Folder Fallbacks
        parent = file_path.parent
        grandparent = parent.parent
        
        # Fallback for Album if missing or garbage
        if not album or all(c == '?' or c == ' ' for c in str(album)):
            if parent.name.lower() not in ["library", "e-music", "music"]:
                album = parent.name
            else:
                album = "Unknown Album"

        # Fallback for Artist if missing or garbage
        if not artist or all(c == '?' or c == ' ' for c in str(artist)):
            if grandparent.name.lower() not in ["library", "e-music", "music"]:
                # Structure: .../Artist/Album/Track.mp3
                artist = grandparent.name
            elif parent.name.lower() not in ["library", "e-music", "music"]:
                # Structure: .../Artist/Track.mp3
                artist = parent.name
            else:
                artist = "Unknown Artist"

        # Sanity check for title
        if title and all(c == '?' or c == ' ' for c in str(title)):
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
                source_type="local",
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
    from app.config import settings
    cache_path = Path(settings.CACHE_DIR)
    
    with Session(engine) as session:
        for file_path in library_dir.rglob("*.mp3"):
            # Skip if file is inside the cache directory
            if cache_path in file_path.parents:
                continue
            scan_file(file_path, session)
    _logger.info("Library scan complete")

def run_indexer() -> None:
    """
    Convenience function to run the indexer on the default library path.
    """
    from app.config import settings
    scan_library(settings.MUSIC_PATH)
