"""
Repair stale track rows: phantom \"cached\" flags and junk indexed from temp/cache dirs.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlmodel import Session, col, delete, select

from app.config import settings
from app.db import engine
from app.models import PlaylistTrack, Track, UserActivity
from app.utils.logger import setup_logger

_logger = setup_logger(__name__)


def _resolved(path: Path) -> Path:
    try:
        return path.resolve(strict=False)
    except OSError:
        return path


def _path_under_any_root(file_path_str: str, roots: list[Path]) -> bool:
    try:
        f = _resolved(Path(file_path_str))
    except OSError:
        f = Path(file_path_str)
    for root in roots:
        try:
            r = _resolved(root)
            if f == r or f.is_relative_to(r):
                return True
        except ValueError:
            continue
    return False


def repair_stale_tracks() -> dict:
    """
    - Delete ``local`` track rows that were indexed from CACHE_DIR or TEMP_DIR but
      the file is gone (typical ``temp_cache`` / video-id title junk).
    - For any other row with a missing ``local_path`` file, clear ``is_cached`` and
      ``local_path`` so the UI matches disk (YouTube rows are kept).
    - Clear ``is_cached`` when it is true but ``local_path`` is empty.
    """
    roots = [_resolved(Path(settings.CACHE_DIR)), _resolved(Path(settings.TEMP_DIR))]

    deleted = 0
    cleared_missing = 0
    cleared_orphan_flag = 0

    with Session(engine) as session:
        tracks = list(session.exec(select(Track)).all())
        for t in tracks:
            if t.local_path:
                if os.path.isfile(t.local_path):
                    continue
                under_cache = _path_under_any_root(t.local_path, roots)
                if t.source_type == "local" and under_cache:
                    session.execute(
                        delete(PlaylistTrack).where(col(PlaylistTrack.track_id) == t.id)
                    )
                    session.execute(
                        delete(UserActivity).where(col(UserActivity.track_id) == t.id)
                    )
                    session.delete(t)
                    deleted += 1
                    _logger.info(
                        "Removed stale indexed cache row id=%s path=%s",
                        t.id,
                        t.local_path,
                    )
                else:
                    t.is_cached = False
                    t.local_path = None
                    session.add(t)
                    cleared_missing += 1
            elif t.is_cached:
                t.is_cached = False
                session.add(t)
                cleared_orphan_flag += 1

        session.commit()

    return {
        "deleted_stale_cache_index_rows": deleted,
        "cleared_missing_file_refs": cleared_missing,
        "cleared_orphan_cache_flags": cleared_orphan_flag,
    }
