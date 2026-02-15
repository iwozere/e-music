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
        if existing:
            return

        audio = MP3(file_path, ID3=ID3)
        
        title = audio.get("TIT2", [file_path.stem])[0]
        artist = audio.get("TPE1", [None])[0]
        album = audio.get("TALB", [None])[0]
        duration = int(audio.info.length) if audio.info else None

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
        session.commit()
        _logger.info("Indexed new track: %s", file_path.name)
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
