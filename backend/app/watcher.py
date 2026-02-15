import time
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileMovedEvent
from sqlmodel import Session

from app.db import engine
from app.indexer import scan_file
from app.utils.logger import setup_logger

_logger = setup_logger(__name__)

class LibraryHandler(FileSystemEventHandler):
    """
    Event handler for monitoring music library filesystem changes.
    """
    def on_created(self, event: FileCreatedEvent) -> None:
        """
        Handle new file creation.
        """
        if not event.is_directory:
            _logger.info("New file detected: %s", event.src_path)
            with Session(engine) as session:
                scan_file(Path(event.src_path), session)

    def on_moved(self, event: FileMovedEvent) -> None:
        """
        Handle file relocation.
        """
        if not event.is_directory:
            _logger.info("File moved: from %s to %s", event.src_path, event.dest_path)
            with Session(engine) as session:
                scan_file(Path(event.dest_path), session)

def start_watcher(library_path: str) -> None:
    """
    Initialize and start the filesystem observer for the music library.

    Args:
        library_path: Absolute path to the library directory to monitor.
    """
    event_handler = LibraryHandler()
    observer = Observer()
    observer.schedule(event_handler, library_path, recursive=True)
    observer.start()
    _logger.info("Library watcher started on %s", library_path)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        _logger.info("Library watcher stopping...")
        observer.stop()
    observer.join()
