# MySpotify v3 — Brainstorm: More sources & faster YouTube playback

This document captures improvement ideas discussed while analyzing the current
state of the app. It is a wish-list / discussion draft, not a commitment. For
authoritative API and deployment info, see
[system_specification.md](system_specification.md) and [docker.md](docker.md).

Related prior docs:
- [requirements.md](requirements.md) — original product requirements.
- [featurev_v2.md](featurev_v2.md) — "quick wins" UX phase.

---

## Implementation status

| Item | Status | Notes |
| :--- | :----- | :---- |
| **§2 — Fast YouTube playback (resolver + passthrough + low-latency ffmpeg)** | **In testing (unshipped)** | Implemented: `yt_resolver.py`, rewritten `streamer.py`, container-aware `Content-Type`, multi-extension cache lookup, legacy subprocess kept behind `STREAM_FORCE_LEGACY_SUBPROCESS`. Web UI `v2.9.18`. Config flags: `STREAM_LOW_LATENCY`, `STREAM_PASSTHROUGH`, `STREAM_ANALYZEDURATION_US`, `STREAM_PROBESIZE_BYTES`, `STREAM_TRANSCODE_BITRATE_KBPS`, `YTDLP_RESOLVED_URL_TTL_SEC`. Unit tests: `test_yt_resolver.py`, `test_streamer_pipeline.py` (21 tests). **Pending manual validation on Pi 5 + field tests across diverse YouTube formats/browsers.** |
| **§2 item 4 — Next-track prefetch** | **In testing (unshipped)** | Implemented: `streamer.prefetch_youtube` + `POST /api/v1/tracks/{track_id}/prefetch`; client schedules a prefetch ~3 s after each successful play; dedup via `_active_downloads` + `BoundedSemaphore(PREFETCH_MAX_CONCURRENT)`. Config flags: `PREFETCH_ENABLED`, `PREFETCH_MAX_CONCURRENT`. Unit tests: `test_prefetch.py` (6 tests). **Pending manual validation + metered-network behavior checks.** |
| **§2 item 7 — HTTP Range on live YouTube proxy** | **Deferred** | Explicitly out of scope for the first pass; cached/local files still support Range via `FileResponse`. |
| Everything else in this doc | **Backlog** | See §3–§5. |

---

## 1. How music is fetched today

- **Local library** — indexer walks `MUSIC_PATH` (`/share/e-music/library`);
  watcher re-scans on change; served via `FileResponse` with HTTP Range support
  (`backend/app/services/streamer.py` → `get_local_stream`).
- **YouTube Music** — search via `ytmusicapi`
  (`backend/app/services/ytmusic.py`); playback via a
  `yt-dlp → ffmpeg → HTTP` pipe in `streamer.stream_youtube`, with a
  "3 plays promotes to persistent cache" rule
  (`backend/app/routers/tracks.py` + `services/cache_manager.py`).

`Track.source_type` today is only `'local' | 'youtube'`.

---

## 2. Why YouTube playback takes 10–20 seconds to start

The cold-start latency is the sum of several avoidable delays in
`backend/app/services/streamer.py`.

### a. `yt-dlp` subprocess cold start (~3–8 s on a Pi 5)
Every play spawns a brand-new `yt-dlp` process (`_build_yt_dlp_argv`), which
imports all extractors, resolves the video, negotiates with YouTube, and
iterates over `player_client=tv_embedded,web,mweb`. This happens even for
tracks just played.

### b. ffmpeg probe window — the single biggest factor
`_build_ffmpeg_transcode_argv` uses:

```
-analyzeduration 10000000
-probesize       10000000
```

That tells ffmpeg to read up to **10 MB / 10 s of input before producing any
output**. Combined with `_pull_first_chunk` awaiting the very first byte,
nothing reaches the browser until that probe completes.

### c. Unnecessary transcode to MP3
YouTube audio is already Opus (webm) or AAC (m4a), both supported natively by
Chrome/Safari/Edge. Instead we re-encode to `libmp3lame @ 128 kbps` — expensive
on a Pi and forces the full pipeline to run before the first chunk.

### d. No HTTP Range, no Content-Length
`Accept-Ranges: none` on the YouTube path means the browser can't
stream-and-seek; some clients buffer more conservatively before they start
playback.

### e. No warm-up / prefetch
The next track in the queue is only resolved when the user clicks it. Meanwhile
the queue is already known client-side in `player.js`.

### f. Duplicate work on resolution
`ytmusicapi` has already returned a `videoId`; `yt-dlp` then does its own HTTP
roundtrip to resolve that same id into a format URL.

### Fixes, ranked by impact vs. effort

| # | Change | Expected win |
| - | - | - |
| 1 | Drop `-analyzeduration/-probesize` to `500000`/`500000` (or `32k`/`32k` for Opus/AAC) and add `-fflags nobuffer -flags low_delay -avioflags direct` | **-5 to -8 s** |
| 2 | Replace MP3 transcode with **stream-copy** (`-c:a copy`) to fMP4/ADTS/WebM. `audio/webm` and `audio/mp4` are supported in every modern browser. Fall back to transcode only when the source codec isn't playable | **-3 to -6 s** + Pi CPU win |
| 3 | Use the yt-dlp **Python API** inside the FastAPI process (reuse one `YoutubeDL` instance); call `extract_info(..., download=False)` to get the direct `googlevideo` URL, then stream it with `httpx.AsyncClient` into ffmpeg (or directly to the client if 2 is done) | **-2 to -4 s** (no subprocess import) |
| 4 | **Prefetch/warm cache** next track(s) in `state.queue` and the predicted next from `currentTracksContext`. A small background job in `tracks.py` can call `streamer.stream_youtube` headlessly so the file is already in `TEMP_DIR` | **~0 s** for the next track |
| 5 | **Cache resolved format URL** (`video_id → direct URL`, TTL ~5 h) so repeated plays skip resolution entirely | **-1 to -3 s** |
| 6 | Pre-resolve top search results lazily (e.g., top 3 on hover / scroll) | **-1 to -3 s** |
| 7 | Support Range requests on the proxy path: when `Range` is present and we have a resolved URL, proxy bytes with a matching Range; seeks work without full re-download | better UX |
| 8 | Return an `audio/webm` or `audio/mp4` `Content-Type` that matches the chosen stream (today it's hard-coded `audio/mpeg`) | avoids silent buffering |

Changes **1 + 2** alone should bring typical YouTube first-sound latency well
below 3 s on a Pi 5.

**OS/infra side:** ship a pinned `yt-dlp` in the Docker image, auto-updated on
every build — outdated `yt-dlp` is the single biggest cause of sudden
extraction slowdowns.

---

## 3. Other places to get music from

All of these are free/legal and integrate cleanly with the current `source_type`
design. Most are one-line yt-dlp changes.

### Same pipeline as YouTube (yt-dlp already supports)
- **SoundCloud** — official streams, very fast to resolve.
- **Bandcamp** — full tracks / album streams where the artist allows.
- **Mixcloud** — DJ sets and shows.
- **Audius** — decentralized; has a direct streaming API.
- **Internet Archive / Live Music Archive** — huge CC/PD catalog (Grateful
  Dead, live concerts, old jazz, public-domain classical).

### Direct APIs, no yt-dlp needed (cleaner + faster than YouTube)
- **Jamendo API** — CC-licensed music, direct MP3 URLs.
- **Free Music Archive / ccMixter** — direct MP3s.
- **Radio Browser API + Icecast/Shoutcast** — thousands of live radio streams,
  zero startup latency (direct proxy).
- **SomaFM / Radio Paradise** — curated streams with nice metadata JSON.
- **Podcast RSS feeds** — one endpoint, direct MP3 enclosures; opens a whole
  new vertical.
- **Deezer / Spotify previews** — 30-second previews only (discovery, not
  playback).

### User-owned clouds (big UX win, zero legal worries)
- **User MP3 upload** endpoint writing straight into
  `/library/{user}/...` (rate-limited, size-capped).
- **WebDAV / Nextcloud / rclone mounts** — treat as an additional indexed path.
- **Google Drive / Dropbox / OneDrive** via user OAuth — stream from there,
  cache locally.

### Metadata & discovery (not sources, but make the library better)
- **MusicBrainz + AcoustID/Chromaprint** — auto-tag local files, dedupe, find
  correct artist/album.
- **Last.fm / ListenBrainz** — scrobbling + real recommendations that aren't
  just "YouTube related".
- **Cover Art Archive / fanart.tv** — proper album artwork instead of the
  Unsplash placeholder used in `player.js`.

**Implementation shape:** extend `Track.source_type` (e.g.
`'local' | 'youtube' | 'soundcloud' | 'bandcamp' | 'radio' | 'podcast' |
'upload' | 'drive'`) and generalize `streamer.stream_youtube` into a dispatcher
keyed by `source_type`. URL-signing and cache-promotion logic stay identical.

---

## 4. Other improvement ideas

Grouped so you can pick what resonates. Items marked ⭐ are the highest ROI.

### Playback & UX (web)
- ⭐ **Gapless + crossfade** by pre-loading the next track into a hidden
  `<audio>` (trivial with the queue already tracked).
- ⭐ **Media Session action handlers** and `setPositionState` — featurev_v2
  table says partial; lock-screen controls, seek, and prev/next still missing.
- ⭐ **Keyboard shortcuts** (Space / arrows / M) — still "Not done".
- **Autoplay radio on queue end** — backend endpoint
  `/tracks/{id}/related` already exists; wire it into `playNext` when the queue
  empties.
- **Persist queue and last-played position** in `localStorage` → resume on
  refresh.
- **Mini-player** on small viewports.
- **Drag-and-drop queue reorder**.
- **Search-as-you-type with cancellation** — current search fires on Enter;
  debounce + `AbortController` pairs well with cached results (§2, item 6).
- **Lyrics tab** — lrclib.net API, free, cached locally.
- **Visualizer / spectrum** using WebAudio.

### Backend & infra
- **Make `MAX_CACHE_SIZE_GB` env-configurable** and evict based on
  `UserActivity.play_count` instead of `atime` (current eviction fights the
  "popular" rule — known gap in featurev_v2).
- **Update DB when cache file is deleted** (eviction currently leaves
  `is_cached=True` rows pointing at missing files; `tracks.py` has defensive
  code but the DB still drifts).
- **Subsonic / OpenSubsonic API compatibility** — free, massive win: unlocks
  Symfonium, DSub, play:Sub, Feishin, Supersonic, Tempo, Substreamer, Sonixd
  on every platform. The existing data model maps cleanly.
- **Jellyfin music plugin parity** as an alternative.
- **Background library scan metrics** endpoint (files indexed, errors) for the
  admin page.
- **Observability** — wire `X-Request-ID` through to toasts so users can paste
  an id when something fails (`player.js` `fetchStreamErrorDetail`).
- **Rate-limit the YouTube search cache smarter** — `SEARCH_CACHE` dict in
  `tracks.py` grows forever; use TTL-evicted LRU with a size cap.
- **Scale path** — SQLite + Litestream for cheap replication, or Postgres when
  you outgrow a Pi.

### Mobile
- **Flutter background playback** using `just_audio` + `audio_service` with the
  grant-URL flow (spec already mentions this).
- **Offline-first** — playlists flagged `is_offline` should proactively fetch
  and persist tracks on Wi-Fi; schema already has `Playlist.is_offline` but no
  sync worker.
- **Chromecast / AirPlay** targets — `just_audio` + platform channels.
- **Android Auto / CarPlay** via `audio_service` / `MPNowPlayingInfoCenter`.
- **Home-screen widget / glance tile** with now-playing.

### Personalization
- **Recommendations** from `UserActivity` — most-played this week, new since
  last login, "forgotten gems" (liked but not played in 90 days).
- **Smart playlists** — "Liked + played 3+ times + not played in 30 days".
- **Per-household profiles** — the schema already supports multi-user; the UI
  doesn't lean into it.

### Privacy / cost / legal
- Consider **Piped / Invidious** as a YouTube front-end to reduce IP-blocking
  risk and insulate us from yt-dlp version churn.
- **Cookies file** support is already there (`YTDLP_COOKIES_FILE`); surface it
  in the admin page with an upload form so it can be refreshed without SSH.
- Document the "personal / family use" stance in README so contributors
  understand scope.

---

## 5. Suggested sequencing

1. ~~**Kill the delay** — §2 items 1 + 2 (ffmpeg probe window + stream-copy).~~ **In testing.**
2. ~~**Warm cache / prefetch** — §2 item 4. Next track starts instantly.~~ **In testing.**
3. ~~**Resolved-URL cache** — §2 item 5. Repeat plays feel local.~~ **In testing** (bundled with item 1, same TTL cache in `yt_resolver.py`).
4. **Source dispatcher refactor** — §3. Unlocks SoundCloud / Bandcamp / radio /
   podcasts with the same signed-URL + cache machinery.
5. **Finish featurev_v2** — Media Session actions + keyboard shortcuts +
   autoplay radio on queue end.
6. **Subsonic API surface** — multiplies the number of clients without us
   writing them.
