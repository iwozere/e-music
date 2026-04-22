"""Unit tests for ``app.services.yt_resolver`` (no network, no yt-dlp)."""

# Tests legitimately poke at module privates (``_cache``, ``_pick_audio_format``,
# ``_PhaseRecorder``, etc.) and their function names are self-documenting. We
# also prefer explicit ``== []`` assertions (stricter than truthiness — they
# distinguish ``None`` from ``[]``), so silence the corresponding Pylint rules
# for this file only.
# pylint: disable=protected-access,missing-function-docstring,use-implicit-booleaness-not-comparison

from __future__ import annotations

import asyncio
import contextvars
import logging
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
    monkeypatch.setattr(yt_resolver, "_resolve_sync", lambda _vid: None)

    async def run():
        res = await yt_resolver.resolve("badid")
        assert res is None
        assert "badid" not in yt_resolver._cache  # noqa: SLF001

    asyncio.run(run())


def test_resolver_handles_empty_video_id():
    async def run():
        assert (await yt_resolver.resolve("")) is None

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Phase-timing recorder
# ---------------------------------------------------------------------------


def test_phase_recorder_captures_known_phases_in_order():
    rec = yt_resolver._PhaseRecorder(video_id="VID")  # noqa: SLF001
    # Simulate the exact message strings yt-dlp prints during a typical
    # YouTube extraction (drawn from a real prod log).
    messages = [
        "[youtube] VID: Downloading webpage",
        "[youtube] VID: Downloading tv client config",
        "[youtube] VID: Downloading tv player API JSON",
        "[youtube] VID: Downloading player abc123.js",
        "[youtube] VID: Decrypting signature",
        "[youtube] VID: Downloading web client config",       # fallback tried second
        "[youtube] VID: Downloading web player API JSON",
    ]
    for m in messages:
        rec.info(m)

    names = [ev.name for ev in rec.events]
    assert "webpage" in names
    assert "client_cfg:tv" in names
    assert "player_api:tv" in names
    assert "player_js" in names
    assert "signature" in names
    assert "client_cfg:web" in names
    assert "player_api:web" in names

    assert rec.clients == ["tv", "web"]

    ms_by_name = {ev.name: ev.ms for ev in rec.events}
    # Order must be non-decreasing (we record in emission order).
    offsets = [ev.ms for ev in rec.events]
    assert offsets == sorted(offsets)
    assert ms_by_name["webpage"] <= ms_by_name["client_cfg:tv"]


def test_phase_recorder_deduplicates_and_ignores_unknown():
    rec = yt_resolver._PhaseRecorder(video_id="VID")  # noqa: SLF001
    rec.info("[youtube] VID: Downloading webpage")
    rec.info("[youtube] VID: Downloading webpage")  # duplicate — should be ignored
    rec.debug("unrelated chatter from some plugin")  # no Downloading/etc. — ignored

    names = [ev.name for ev in rec.events]
    assert names == ["webpage"]
    assert rec.clients == []


def test_phase_recorder_captures_js_runtime_and_po_token_phases():
    """Covers the ~8 s gap that used to follow ``player_api:mweb``."""
    rec = yt_resolver._PhaseRecorder(video_id="VID")  # noqa: SLF001
    messages = [
        # Newer yt-dlp drops the ``.js`` suffix — both forms must classify as
        # ``player_js`` (otherwise it falls through to ``misc:player``).
        "[youtube] VID: Downloading player abc123",
        "[youtube] VID: Extracting signature function",
        "[youtube] VID: Decrypting signature",
        "[youtube] VID: Extracting n function",
        "[youtube] VID: Testing n function with player response",
        "[youtube] VID: Fetching PO token",
        "[debug] yt-dlp-ejs: loading JS runtime (Deno)",
        "[info] VID: Downloading 1 format(s): 140",
    ]
    for m in messages:
        rec.info(m)

    names = [ev.name for ev in rec.events]
    assert "player_js" in names
    assert "signature" in names
    assert "nsig" in names
    assert "po_token" in names
    assert "ejs" in names
    assert "format_select" in names
    # The catch-all must NOT have fired for ``Downloading player abc123``.
    assert not any(n.startswith("misc:") for n in names), names


def test_phase_recorder_catchall_buckets_unknown_downloads():
    """Unknown ``Downloading X`` lines still get timed as ``misc:<slug>``."""
    rec = yt_resolver._PhaseRecorder(video_id="VID")  # noqa: SLF001
    rec.info("[youtube] VID: Downloading webpage")               # known
    rec.info("[youtube] VID: Downloading brand_new_phase")       # unknown
    rec.info("[youtube] VID: Downloading brand_new_phase")       # duplicate — dropped
    rec.info("[youtube] VID: Downloading another_mystery")       # unknown #2

    names = [ev.name for ev in rec.events]
    assert names == ["webpage", "misc:brand_new_phase", "misc:another_mystery"]


def test_phase_recorder_tolerates_non_string_input():
    rec = yt_resolver._PhaseRecorder(video_id="VID")  # noqa: SLF001
    rec.info(None)                     # type: ignore[arg-type]
    rec.info(42)                       # type: ignore[arg-type]
    rec.info({"not": "a string"})      # type: ignore[arg-type]
    rec.info("")                       # empty string
    assert rec.events == []


def test_fmt_timing_produces_compact_string():
    events = [
        yt_resolver._PhaseEvent(name="webpage", ms=180),              # noqa: SLF001
        yt_resolver._PhaseEvent(name="client_cfg:tv", ms=260),        # noqa: SLF001
        yt_resolver._PhaseEvent(name="signature", ms=1850),           # noqa: SLF001
    ]
    assert yt_resolver._fmt_timing(events) == (  # noqa: SLF001
        "webpage@180,client_cfg:tv@260,signature@1850"
    )
    assert yt_resolver._fmt_timing([]) == ""  # noqa: SLF001


def test_dispatch_logger_forwards_only_to_current_context_recorder():
    """Concurrent resolves via different contexts must not cross-pollute."""
    rec_a = yt_resolver._PhaseRecorder(video_id="A")  # noqa: SLF001
    rec_b = yt_resolver._PhaseRecorder(video_id="B")  # noqa: SLF001

    ctx_a = contextvars.copy_context()
    ctx_b = contextvars.copy_context()
    ctx_a.run(yt_resolver._recorder_ctx.set, rec_a)   # noqa: SLF001
    ctx_b.run(yt_resolver._recorder_ctx.set, rec_b)   # noqa: SLF001

    ctx_a.run(yt_resolver._dispatch_logger.info,      # noqa: SLF001
              "[youtube] A: Downloading webpage")
    ctx_b.run(yt_resolver._dispatch_logger.info,      # noqa: SLF001
              "[youtube] B: Downloading tv client config")

    assert [ev.name for ev in rec_a.events] == ["webpage"]
    assert [ev.name for ev in rec_b.events] == ["client_cfg:tv"]


def test_resolve_log_includes_phase_timing(monkeypatch, caplog):
    """End-to-end: a successful resolve emits phase timing in its log line."""
    def fake_resolve_sync(video_id: str):
        # Emulate what yt-dlp would do: emit a few messages via the dispatch
        # logger in the *same thread/context* (asyncio.to_thread propagates
        # contextvars), then return a ResolvedFormat.
        yt_resolver._dispatch_logger.info(                      # noqa: SLF001
            f"[youtube] {video_id}: Downloading webpage"
        )
        yt_resolver._dispatch_logger.info(                      # noqa: SLF001
            f"[youtube] {video_id}: Downloading tv client config"
        )
        yt_resolver._dispatch_logger.info(                      # noqa: SLF001
            f"[youtube] {video_id}: Downloading tv player API JSON"
        )
        return ResolvedFormat(
            video_id=video_id,
            url=f"https://example.test/{video_id}",
            ext="m4a",
            acodec="mp4a.40.2",
            http_headers={},
            expires_at=time.monotonic() + 3600,
        )

    monkeypatch.setattr(yt_resolver, "_resolve_sync", fake_resolve_sync)

    caplog.set_level(logging.INFO, logger=yt_resolver._logger.name)  # noqa: SLF001

    async def run():
        res = await yt_resolver.resolve("abc42")
        assert res is not None

    asyncio.run(run())

    info_msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert any("yt_resolver: resolved" in m for m in info_msgs)
    # The enriched line must carry the phase breakdown + client list.
    combined = "\n".join(info_msgs)
    assert "cache=miss" in combined
    assert "clients=tv" in combined
    assert "timing=" in combined
    assert "webpage@" in combined
    assert "client_cfg:tv@" in combined
    assert "player_api:tv@" in combined
