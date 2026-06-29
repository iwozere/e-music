"""Keep yt-dlp current in the Standalone Edition (docs/features-v7.md §3.3).

YouTube changes frequently break older yt-dlp builds. A frozen desktop app can't ``pip
install -U`` itself, so instead we download yt-dlp's official self-contained zipapp (the
``yt-dlp`` release asset, which is an importable zip) into the user data dir and put it
*ahead* of the bundled copy on ``sys.path``. ``import yt_dlp`` then loads the newer code.

Everything here is best-effort: any failure leaves the bundled yt-dlp in place.
"""

import os
import sys
import threading
import time
import urllib.request
import zipfile

# Official self-contained build (a zip with a shebang; zipimport tolerates the leading bytes).
_RELEASE_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp"
_REFRESH_INTERVAL_SEC = 24 * 3600
_DOWNLOAD_TIMEOUT_SEC = 30


def _paths(data_dir: str) -> tuple[str, str, str]:
    base = os.path.join(data_dir, "yt-dlp")
    return base, os.path.join(base, "yt-dlp"), os.path.join(base, "last_check")


def prepare_ytdlp(data_dir: str, logger=None) -> None:
    """Activate a cached newer yt-dlp (if any) and refresh it in the background when stale.

    Must be called *before* anything imports ``yt_dlp``.
    """
    if not data_dir:
        return
    base, archive, stamp = _paths(data_dir)

    if os.path.isfile(archive) and _looks_valid(archive):
        if archive not in sys.path:
            sys.path.insert(0, archive)
            _log(logger, "info", "yt-dlp: using updated build from %s", archive)

    if _is_stale(stamp):
        threading.Thread(
            target=_refresh, args=(base, archive, stamp, logger), daemon=True
        ).start()


def _is_stale(stamp: str) -> bool:
    try:
        return (time.time() - os.path.getmtime(stamp)) > _REFRESH_INTERVAL_SEC
    except OSError:
        return True  # never checked


def _looks_valid(path: str) -> bool:
    """A usable archive is a valid zip that contains the ``yt_dlp`` package."""
    try:
        if not zipfile.is_zipfile(path):
            return False
        with zipfile.ZipFile(path) as zf:
            return any(name.startswith("yt_dlp/") for name in zf.namelist())
    except (OSError, zipfile.BadZipFile):
        return False


def _refresh(base: str, archive: str, stamp: str, logger) -> None:
    """Download the latest yt-dlp to a temp file, validate it, then atomically swap it in."""
    try:
        os.makedirs(base, exist_ok=True)
        tmp = archive + ".download"
        req = urllib.request.Request(_RELEASE_URL, headers={"User-Agent": "MySpotify-Standalone"})
        with urllib.request.urlopen(req, timeout=_DOWNLOAD_TIMEOUT_SEC) as resp:  # noqa: S310
            data = resp.read()
        with open(tmp, "wb") as fh:
            fh.write(data)

        if not _looks_valid(tmp):
            os.remove(tmp)
            _log(logger, "warning", "yt-dlp: downloaded archive failed validation; keeping current")
            return

        os.replace(tmp, archive)
        # Touch the stamp so we don't re-check for another day (success or not).
        with open(stamp, "w", encoding="utf-8") as fh:
            fh.write(str(int(time.time())))
        _log(logger, "info", "yt-dlp: updated (effective on next launch)")
    except Exception as exc:  # network down, GitHub hiccup, disk full — all non-fatal
        _log(logger, "warning", "yt-dlp: update check failed: %s", exc)


def _log(logger, level: str, msg: str, *args) -> None:
    if logger is not None:
        getattr(logger, level, lambda *_: None)(msg, *args)
