"""Unit tests for the ffmpeg argv builders and cache-artifact picking in streamer.py.

These do NOT spawn ffmpeg or yt-dlp; they only validate command shape + config-driven
decisions, which is where regressions in Feature 1 would bite.
"""

from __future__ import annotations

import time

import pytest

from app.config import settings
from app.services import streamer
from app.services.yt_resolver import ResolvedFormat


def _make_resolved(*, ext: str = "m4a", acodec: str = "mp4a.40.2") -> ResolvedFormat:
    return ResolvedFormat(
        video_id="abc12345",
        url="https://example.test/stream",
        ext=ext,
        acodec=acodec,
        http_headers={},
        expires_at=time.monotonic() + 600,
    )


# ---------------------------------------------------------------------------
# ffmpeg argv builders
# ---------------------------------------------------------------------------


def test_passthrough_argv_opus_webm():
    argv = streamer._build_ffmpeg_passthrough_argv("webm")  # noqa: SLF001
    # ffmpeg binary path varies across platforms (Windows uses ``ffmpeg.EXE``).
    assert "ffmpeg" in argv[0].lower()
    assert "-c:a" in argv and "copy" in argv
    assert "-f" in argv and "webm" in argv
    assert "pipe:0" in argv and "pipe:1" in argv
    # Probe size must be the small, config-driven value (not the legacy 10_000_000).
    assert str(int(settings.STREAM_PROBESIZE_BYTES)) in argv
    assert "libmp3lame" not in argv


def test_passthrough_argv_aac_adts():
    argv = streamer._build_ffmpeg_passthrough_argv("adts")  # noqa: SLF001
    assert "-f" in argv and "adts" in argv
    assert "-c:a" in argv and "copy" in argv


def test_passthrough_argv_mp4_has_fragmenting_flags():
    argv = streamer._build_ffmpeg_passthrough_argv("mp4")  # noqa: SLF001
    assert "-movflags" in argv
    idx = argv.index("-movflags")
    assert "frag_keyframe" in argv[idx + 1]


def test_passthrough_argv_rejects_unknown_container():
    with pytest.raises(ValueError):
        streamer._build_ffmpeg_passthrough_argv("flac")  # noqa: SLF001


def test_transcode_argv_uses_config_bitrate():
    argv = streamer._build_ffmpeg_transcode_argv()  # noqa: SLF001
    kbps = max(64, int(settings.STREAM_TRANSCODE_BITRATE_KBPS))
    assert f"{kbps}k" in argv
    assert "libmp3lame" in argv
    assert "-f" in argv and "mp3" in argv


def test_common_prefix_honors_low_latency_flag(monkeypatch):
    monkeypatch.setattr(settings, "STREAM_LOW_LATENCY", True)
    argv = streamer._common_ffmpeg_prefix()  # noqa: SLF001
    assert "-fflags" in argv and "nobuffer" in argv
    assert "-flags" in argv and "low_delay" in argv

    monkeypatch.setattr(settings, "STREAM_LOW_LATENCY", False)
    argv = streamer._common_ffmpeg_prefix()  # noqa: SLF001
    assert "nobuffer" not in argv
    assert "low_delay" not in argv


def test_common_prefix_uses_small_probe_window():
    argv = streamer._common_ffmpeg_prefix()  # noqa: SLF001
    # Crucial: must NOT be the legacy 10_000_000 (root cause of the 10-20 s delay).
    assert "10000000" not in argv


# ---------------------------------------------------------------------------
# Cache extension / media-type picker
# ---------------------------------------------------------------------------


def test_cache_ext_for_aac_passthrough(monkeypatch):
    monkeypatch.setattr(settings, "STREAM_PASSTHROUGH", True)
    ext, media, container = streamer._cache_ext_and_media_type(_make_resolved())  # noqa: SLF001
    assert ext == ".aac"
    assert media == "audio/aac"
    assert container == "adts"


def test_cache_ext_for_opus_passthrough(monkeypatch):
    monkeypatch.setattr(settings, "STREAM_PASSTHROUGH", True)
    opus = _make_resolved(ext="webm", acodec="opus")
    ext, media, container = streamer._cache_ext_and_media_type(opus)  # noqa: SLF001
    assert ext == ".webm"
    assert media == "audio/webm"
    assert container == "webm"


def test_cache_ext_falls_back_to_mp3_when_passthrough_disabled(monkeypatch):
    monkeypatch.setattr(settings, "STREAM_PASSTHROUGH", False)
    ext, media, container = streamer._cache_ext_and_media_type(_make_resolved())  # noqa: SLF001
    assert ext == ".mp3"
    assert media == "audio/mpeg"
    assert container == "mp3"


def test_cache_ext_falls_back_to_mp3_for_unknown_codec(monkeypatch):
    monkeypatch.setattr(settings, "STREAM_PASSTHROUGH", True)
    flac = _make_resolved(ext="flac", acodec="flac")
    ext, media, container = streamer._cache_ext_and_media_type(flac)  # noqa: SLF001
    assert ext == ".mp3"
    assert media == "audio/mpeg"
    assert container == "mp3"


def test_cache_ext_mp3_when_no_resolved_format():
    ext, media, container = streamer._cache_ext_and_media_type(None)  # noqa: SLF001
    assert (ext, media, container) == (".mp3", "audio/mpeg", "mp3")


def test_cached_artifact_paths_order():
    paths = streamer._cached_artifact_paths("abc123")  # noqa: SLF001
    # Persistent must appear before temp so the primary serves fast.
    labels = [label for _, _, label in paths]
    assert labels.index("persistent") < labels.index("temp")
    # All supported extensions present somewhere.
    exts = {p.rsplit(".", 1)[-1] for p, _, _ in paths}
    assert {"mp3", "webm", "aac", "m4a"}.issubset(exts)
