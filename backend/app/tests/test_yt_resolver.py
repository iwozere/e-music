"""Unit tests for ``app.services.yt_resolver`` (no network, no yt-dlp)."""

from __future__ import annotations

import time

import pytest

from app.services import yt_resolver
from app.services.yt_resolver import ResolvedFormat


@pytest.fixture(autouse=True)
def _clear_cache():
    yt_resolver._cache.clear()  # noqa: SLF001
    yield
    yt_resolver._cache.clear()  # noqa: SLF001


def test_pick_audio_format_prefers_m4a_over_opus():
    info = {
        "formats": [
            {"ext": "webm", "acodec": "opus", "vcodec": "none", "abr": 160, "url": "u-opus"},
            {"ext": "m4a", "acodec": "mp4a.40.2", "vcodec": "none", "abr": 128, "url": "u-aac"},
            {"ext": "mp4", "acodec": "mp4a.40.2", "vcodec": "avc1", "abr": 128, "url": "u-muxed"},
        ],
    }
    chosen = yt_resolver._pick_audio_format(info)  # noqa: SLF001
    assert chosen is not None
    assert chosen["url"] == "u-aac", "m4a/AAC should win over opus"


def test_pick_audio_format_falls_back_to_opus():
    info = {
        "formats": [
            {"ext": "webm", "acodec": "opus", "vcodec": "none", "abr": 160, "url": "u-opus"},
            {"ext": "webm", "acodec": "vorbis", "vcodec": "none", "abr": 64, "url": "u-vorbis"},
        ],
    }
    chosen = yt_resolver._pick_audio_format(info)  # noqa: SLF001
    assert chosen is not None
    assert chosen["url"] == "u-opus"


def test_pick_audio_format_uses_flat_info_when_no_formats():
    info = {"url": "u-direct", "ext": "m4a", "acodec": "mp4a.40.2"}
    chosen = yt_resolver._pick_audio_format(info)  # noqa: SLF001
    assert chosen == info


def test_pick_audio_format_returns_none_when_empty():
    assert yt_resolver._pick_audio_format({"formats": []}) is None  # noqa: SLF001


def test_resolved_format_codec_flags():
    opus = ResolvedFormat(
        video_id="v1", url="u", ext="webm", acodec="opus",
        http_headers={}, expires_at=time.monotonic() + 1000,
    )
    aac = ResolvedFormat(
        video_id="v2", url="u", ext="m4a", acodec="mp4a.40.2",
        http_headers={}, expires_at=time.monotonic() + 1000,
    )
    weird = ResolvedFormat(
        video_id="v3", url="u", ext="flac", acodec="flac",
        http_headers={}, expires_at=time.monotonic() + 1000,
    )
    assert opus.is_opus and opus.browser_safe_codec
    assert aac.is_aac and aac.browser_safe_codec
    assert not weird.is_opus and not weird.is_aac and not weird.browser_safe_codec


def test_resolver_cache_roundtrip(monkeypatch):
    """resolve() caches successful results and invalidate() drops them."""
    import asyncio

    calls = {"n": 0}

    def fake_resolve_sync(video_id: str):
        calls["n"] += 1
        return ResolvedFormat(
            video_id=video_id,
            url=f"https://example.test/{video_id}",
            ext="m4a",
            acodec="mp4a.40.2",
            http_headers={"User-Agent": "test"},
            expires_at=time.monotonic() + 3600,
        )

    monkeypatch.setattr(yt_resolver, "_resolve_sync", fake_resolve_sync)

    async def run():
        a = await yt_resolver.resolve("vid123")
        b = await yt_resolver.resolve("vid123")
        assert a is not None and b is not None
        assert a.url == b.url
        assert calls["n"] == 1, "cache hit expected on second call"

        yt_resolver.invalidate("vid123")
        c = await yt_resolver.resolve("vid123")
        assert c is not None and calls["n"] == 2

        d = await yt_resolver.resolve("vid123", force_refresh=True)
        assert d is not None and calls["n"] == 3

    asyncio.run(run())


def test_resolver_returns_none_on_failure(monkeypatch):
    import asyncio

    monkeypatch.setattr(yt_resolver, "_resolve_sync", lambda _vid: None)

    async def run():
        res = await yt_resolver.resolve("badid")
        assert res is None
        assert "badid" not in yt_resolver._cache  # noqa: SLF001

    asyncio.run(run())


def test_resolver_handles_empty_video_id():
    import asyncio

    async def run():
        assert (await yt_resolver.resolve("")) is None

    asyncio.run(run())
