import os
import time
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent
from sqlmodel import Session

from app.db import engine
from app.indexer import scan_file
from app.utils.logger import setup_logger

_logger = setup_logger(__name__)

class LibraryHandler(FileSystemEventHandler):
    """
    Event handler for monitoring music library filesystem changes.
    """
    def on_created(self, event: FileSystemEvent) -> None:
        """
        Handle new file creation.
        """
        if not event.is_directory:
            _logger.info("New file detected: %s", event.src_path)
            with Session(engine) as session:
                scan_file(Path(os.fsdecode(event.src_path)), session)

    def on_moved(self, event: FileSystemEvent) -> None:
        """
        Handle file relocation.
        """
        if not event.is_directory:
            _logger.info("File moved: from %s to %s", event.src_path, event.dest_path)
            with Session(engine) as session:
                scan_file(Path(os.fsdecode(event.dest_path)), session)

def start_watcher(library_path: str) -> None:
    """
    Initialize and start the filesystem observer for the music library.

    Args:
        library_path: Absolute path to the library directory to monitor.
    """
    lib = Path(library_path)
    if not lib.exists():
        try:
            lib.mkdir(parents=True, exist_ok=True)
            _logger.info("Created library directory for watcher: %s", lib)
        except OSError as exc:
            _logger.error(
                "Cannot start library watcher — %s does not exist and could not be "
                "created (%s). In Docker, set MUSIC_PATH to the path inside the "
                "container (e.g. /app/library), matching your volume mount.",
                library_path,
                exc,
            )
            return
    if not lib.is_dir():
        _logger.error(
            "Library path is not a directory; skipping watcher: %s", library_path
        )
        return

    event_handler = LibraryHandler()
    observer = Observer()
    observer.schedule(event_handler, str(lib.resolve()), recursive=True)
    observer.start()
    _logger.info("Library watcher started on %s", lib)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        _logger.info("Library watcher stopping...")
        observer.stop()
    observer.join()
