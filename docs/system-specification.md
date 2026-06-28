# MySpotify: Technical Specification & Feature Documentation

This document is a consolidated technical reference for the MySpotify ecosystem, intended for developers implementing or integrating clients (web, Flutter, future native apps). It should match the current backend in this repository; deployment and Compose operations are described in [docker.md](docker.md).

---

## 1. System architecture overview

MySpotify is a self-hosted music stack with a centralized backend and multiple clients.

| Layer | Stack |
| :---- | :---- |
| **Backend** | FastAPI (Python 3.11 in production Docker image), SQLModel, SQLite |
| **Web UI** | Vanilla JavaScript (ES modules via plain scripts), CSS, [Lucide](https://lucide.dev) icons; served from the backend at `/` and `/static/` (see `backend/app/static/`) |
| **Mobile** | Flutter (Dart), BLoC-style state management (`mobile/`) |
| **Media** | `yt-dlp` for YouTube audio (in-process resolver + subprocess fallback); `ffmpeg` for stream-copy and transcoding; `mutagen` for ID3 tagging |

**API base path:** All JSON endpoints are under **`/api/v1`**. The reference web client uses `window.location.origin + '/api/v1'`.

**Health (unversioned):** `GET /health` returns `{"status": "healthy"}`.

---

## 2. Core features

### 2.1 Unified search & discovery

- **Logic:** Combines local SQLite results with YouTube Music search; merges duplicates when a YouTube `remote_id` matches an indexed track.
- **Pagination:** `offset` and `limit` (default page size in the web UI is 20).
- **Source indicators (web):** Local tracks show a "hard drive" style icon; YouTube-sourced rows show a "cloud" style icon.
- **Cached badge:** YouTube-origin tracks that are stored on server disk (`is_cached`) can be labeled as cached in the UI.

**Search route:** `GET /api/v1/tracks/search?q=...&offset=&limit=`.

### 2.2 Streaming & caching

- **Proxy streaming:** YouTube audio is proxied through the backend (avoids browser CORS and hides client complexity).
- **Signed stream URLs:** Playback does **not** use a long-lived `Authorization` header on the `<audio>` element. Clients must:
  1. `POST /api/v1/tracks/stream/grant` (JWT required) with body `{"track_id": "<id>"}`.
  2. Use the returned `stream_url` (short-lived `exp` / `sig` / `uid` query parameters) as the audio source.
- **Fast playback pipeline:** `yt_resolver` resolves direct `googlevideo` URLs in-process (no subprocess); audio is stream-copied through `ffmpeg` with low-latency flags (`-fflags nobuffer -flags low_delay`, reduced probe windows). Falls back to subprocess transcode when needed.
- **Atomic caching:** Downloads use temporary files and promote to final paths when complete.
- **Play-count promotion:** On **`POST /api/v1/tracks/{track_id}/play`**, after the **third** completed play for a YouTube-backed track (`remote_id` set), the backend promotes it into persistent cache and sets `is_cached = True`.
- **Next-track prefetch:** `POST /api/v1/tracks/{track_id}/prefetch` (JWT) warms the server-side temp cache for a track the client predicts will play next. The web client schedules this ~3 s after a track starts; max 2 concurrent prefetch tasks.
- **Seeking:** Cached/local files support HTTP Range requests; live/proxy paths use chunked streaming.

### 2.3 Playback logic (web dashboard)

- **Queue:** "Add to Queue" and "Play Next" mutate an in-memory queue; the player advances the queue, then continues within `currentTracksContext` (the visible grid/list).
- **Play All / Play Random:** Available for playlist and liked-song contexts in the web UI header.
- **AI Shuffle (Radio Mode):** When the queue and context are exhausted, the web client automatically calls `POST /api/v1/tracks/ai-shuffle` (logged-in users only). The endpoint sends recent listening history to the Groq LLM (Llama 3.1 8B), which returns 10 track suggestions resolved via YouTube Music search. The button `#btn-ai-shuffle` also lets users trigger this on demand.
- **Related tracks:** `GET /api/v1/tracks/{track_id}/related` returns YouTube Music–backed suggestions (available for future client integrations; currently not wired into the main web autoplay loop).

### 2.6 Hum-to-Search (melody identification)

- **Trigger:** Mic icon button in the search bar (web and Flutter mobile).
- **Recording:** Client records 10 seconds of audio (web: `MediaRecorder` → `audio/webm;codecs=opus`; Flutter: `record` package → AAC-LC `.m4a`).
- **Upload:** Multipart `POST /api/v1/ai/identify` with the audio file.
- **Backend:** Audio bytes are sent inline to **Google Gemini** (multimodal model `gemini-2.5-flash` by default). Gemini returns `{artist, title, confidence}` or `{error: not_found}`.
- **Confidence gate:** Results below `IDENTIFY_MIN_CONFIDENCE` (default 75) are treated as not-found.
- **YouTube resolution:** On a confident result, the backend searches YouTube Music for the identified track and returns `{artist, title, confidence, remote_id, thumbnail}`.
- **Client UX:** On success the search field is auto-filled with `"Artist - Title"` and a search is triggered. On failure a snackbar/toast shows the reason.
- **Rate limit:** 3 requests/minute per authenticated user.
- **Auth:** Requires a valid JWT — anonymous access is blocked to protect Gemini API quota.

### 2.4 Organization

- **Liked songs:** Per-user likes via `UserActivity.is_liked` and `GET /api/v1/tracks/liked`.
- **Playlists:** Owner-scoped; tracks ordered by `position` in `PlaylistTrack`.
- **Recently added:** `GET /api/v1/tracks/recent` — tracks ordered by `added_at`.
- **Popular:** `GET /api/v1/tracks/popular` — globally ranked by aggregated play count.

### 2.5 Permanent library import

- **Trigger:** `POST /api/v1/tracks/{track_id}/save-to-library` (JWT). Schedules a background import that downloads the track via yt-dlp, embeds ID3 metadata (title, artist, album, album art), and moves the file to `{MUSIC_PATH}/{Artist}/{Album}/{Track_Title}.mp3`.
- **Case-insensitive dirs:** Artist/album directory resolution is case-insensitive to prevent duplicate folders (e.g. `Smokie` vs `SMOKIE`) on Linux.
- **Sidecar:** Writes `album_meta.json` alongside each album directory for bookkeeping.
- **DB update:** Sets `source_type = 'local'` and `local_path` on the track row; the library watcher auto-indexes the new file.
- **Mobile:** The mobile app stores a copy to internal app storage (`getApplicationDocumentsDirectory()/tracks/{id}.mp3`) for offline playback. Subsequent plays use the local file without a network request.

---

## 3. Backend API specification

### Authentication

- **Mechanisms:** Username/password (`POST /api/v1/auth/register`, `POST /api/v1/auth/token`), Google OAuth (`/auth/login` redirect flow and `/auth/google` direct token verification for mobile/web GSI), and **refresh tokens** (`POST /api/v1/auth/refresh`).
- **JWT:** Send `Authorization: Bearer <access_token>` on API calls (except stream **GET**, which uses the signed URL from **stream/grant**).
- **Token rotation:** Refresh tokens are hashed at rest (`RefreshToken` table); each rotation issues a new pair and invalidates the old.
- **Admin role:** Users whose emails are listed in `ADMIN_EMAILS` (env var) are assigned `role = 'admin'` on login.

### Authentication endpoints

| Endpoint | Method | Auth | Description |
| :------- | :----- | :--- | :---------- |
| `/api/v1/auth/register` | POST | — | Register (username, email, password). 5/min. |
| `/api/v1/auth/token` | POST | — | OAuth2 login; returns access + refresh tokens. 15/min. |
| `/api/v1/auth/refresh` | POST | — | Rotate refresh token. 30/min. |
| `/api/v1/auth/logout` | POST | — | Revoke refresh token (no-op safe). |
| `/api/v1/auth/me` | GET | JWT | Current user profile. |
| `/api/v1/auth/login` | GET | — | Returns Google OAuth2 authorization URL. |
| `/api/v1/auth/callback` | GET | — | Google OAuth2 callback. 30/min. |
| `/api/v1/auth/google` | POST | — | Direct Google ID-token verification (mobile GSI). 30/min. |
| `/api/v1/auth/google/login` | POST | — | Google GSI form-redirect mode. 30/min. |

### Configuration

| Endpoint | Method | Auth | Description |
| :------- | :----- | :--- | :---------- |
| `/api/v1/config` | GET | — | Public client settings (Google client ID, API base URL, version). |

### Tracks & playback

| Endpoint | Method | Auth | Description |
| :------- | :----- | :--- | :---------- |
| `/api/v1/tracks/search` | GET | Optional | Unified search (`q`, `offset`, `limit`). 90/min. |
| `/api/v1/tracks/popular` | GET | Optional | Play-count–ranked tracks. |
| `/api/v1/tracks/recent` | GET | Optional | Recently added (`offset`, `limit`). |
| `/api/v1/tracks/liked` | GET | JWT | Current user's liked tracks. |
| `/api/v1/tracks/stream/grant` | POST | JWT | Returns signed `stream_url` for `track_id`. 120/min. |
| `/api/v1/tracks/stream/{track_id}` | GET | Signed | Audio bytes; requires valid `exp`, `sig`, `uid` from grant. 200/min. |
| `/api/v1/tracks/ai-shuffle` | POST | JWT | LLM-suggested tracks based on context `track_ids`. 10/min. |
| `/api/v1/tracks/{track_id}` | GET | — | Single track metadata. |
| `/api/v1/tracks/{track_id}/like` | POST | JWT | Toggle like (`is_liked` query param). |
| `/api/v1/tracks/{track_id}/play` | POST | Optional | Record play; increments count; may promote to cache on 3rd play. |
| `/api/v1/tracks/{track_id}/related` | GET | — | Related tracks from YouTube Music (radio/autoplay). |
| `/api/v1/tracks/{track_id}/prefetch` | POST | JWT | Warm temp cache for next-track. 120/min. |
| `/api/v1/tracks/{track_id}/save-to-library` | POST | JWT | Trigger background permanent library import. |

**Route ordering note:** `/tracks/ai-shuffle` and other static paths must be registered before `/{track_id}` in the router to prevent FastAPI from matching them as track IDs.

### Playlists

| Endpoint | Method | Auth | Description |
| :------- | :----- | :--- | :---------- |
| `/api/v1/playlists` | GET | JWT | List current user's playlists. |
| `/api/v1/playlists` | POST | JWT | Create playlist (form: `name`). |
| `/api/v1/playlists/{playlist_id}` | DELETE | JWT | Delete playlist. |
| `/api/v1/playlists/{playlist_id}/tracks` | GET | JWT | List tracks (position-ordered; lazy thumbnail backfill). |
| `/api/v1/playlists/{playlist_id}/tracks` | POST | JWT | Add track (form: `track_id`). |
| `/api/v1/playlists/{playlist_id}/tracks/{track_id}` | DELETE | JWT | Remove track from playlist. |

### AI

| Endpoint | Method | Auth | Description |
| :------- | :----- | :--- | :---------- |
| `/api/v1/ai/identify` | POST | JWT | Multipart audio upload → Gemini melody ID → YouTube resolution. Returns `{artist, title, confidence, remote_id, thumbnail}`. 3/min. |

**Request:** `multipart/form-data` with field `audio` containing the audio file. Supported MIME types: `audio/webm`, `audio/mp4`, `audio/mpeg`, `audio/wav`, `audio/ogg`, `audio/opus`, `audio/aac`, `audio/x-m4a`, `audio/x-wav`. Maximum size: 10 MB.

**Responses:**
- `200` — identified: `{"artist": "...", "title": "...", "confidence": 82, "remote_id": "...", "thumbnail": "..."}`
- `422` — not identified (low confidence or Gemini returned not_found)
- `413` — audio file too large
- `415` — unsupported audio format
- `503` — `GEMINI_API_KEY` not configured

### System (admin only)

| Endpoint | Method | Auth | Description |
| :------- | :----- | :--- | :---------- |
| `/api/v1/system/index` | POST | Admin | Trigger background library re-index. |
| `/api/v1/system/repair-stale-tracks` | POST | Admin | Remove phantom cached entries; fix tracks indexed from temp/cache dirs. |
| `/api/v1/system/storage` | GET | Admin | Disk usage summary (`/app`). |

Full request/response shapes and auth requirements are defined in the FastAPI routers under `backend/app/routers/`.

---

## 4. Data models (SQLModel)

### `User`

- `id` (string UUID, PK), `username` (unique), `email` (unique)
- `hashed_password` (optional; null for OAuth-only accounts)
- `role`: `'user'` or `'admin'` (set automatically from `ADMIN_EMAILS`)
- `created_at`

### `Track`

- `id` (string UUID, PK), `title`, `artist`, `album`, `thumbnail`, `duration`
- `source_type`: `'local'` or `'youtube'`
- `remote_id`: YouTube video ID when applicable (unique when set)
- `local_path`: server filesystem path when file exists on disk
- `is_cached`: `True` when file is in persistent cache or library
- `added_at`: used for "Recent" ordering

### `UserActivity` (composite PK: `user_id` + `track_id`)

- `play_count` — incremented on each `/play` call
- `is_liked` — toggled via `/like`
- `last_played`

### `PlayHistory`

- `id` (int, auto-increment PK)
- `user_id` (nullable FK → `User.id`) — null for guest plays
- `track_id` (FK → `Track.id`)
- `played_at` (datetime UTC, indexed)

Used as the input context for AI shuffle: the endpoint looks up the last N entries for the authenticated user to build a listening-history prompt.

### `Playlist` / `PlaylistTrack`

- `Playlist`: `id`, `name`, `owner_id`, `is_offline`, `is_public`
- `PlaylistTrack`: `playlist_id`, `track_id`, `position`

### `RefreshToken`

- Opaque refresh tokens (hashed at rest), tied to `user_id`, with expiry.

---

## 5. Backend services

### `services/streamer.py` — Audio streaming pipeline

- **Primary path:** `yt_resolver` → `httpx` stream → `ffmpeg` stream-copy (opus/aac passthrough).
- **Fallback:** subprocess `yt-dlp | ffmpeg transcode` (toggled via `STREAM_FORCE_LEGACY_SUBPROCESS`).
- **Low-latency flags:** `-fflags nobuffer -flags low_delay`; probe window 500 KB / 500 µs.
- **Temp cache:** LRU-evicted files in `TEMP_DIR`; promoted to `CACHE_DIR` after 3 plays.

### `services/yt_resolver.py` — In-process YouTube URL resolver

- Calls yt-dlp Python API (no subprocess) to get direct `googlevideo` URLs.
- In-memory TTL cache (5 hours); returns `None` on failure → falls back to legacy subprocess.
- Phased timing logs for each resolution step.

### `services/ytmusic.py` — YouTube Music search & metadata

- `search_youtube(query, limit)` — hybrid results with 5-min in-memory TTL cache.
- `get_related_tracks(remote_key)` — radio-style suggestions from YouTube Music.

### `services/ai_shuffle.py` — Groq LLM radio mode

- Sends listening context to Groq API (`llama-3.1-8b-instant` by default; free tier ~14 k req/day).
- Parses JSON response `[{artist, title}, ...]`; resolves each via `search_youtube`.
- Returns 503 if `GROQ_API_KEY` is not configured.

### `services/ai_identify.py` — Gemini melody identification

- `identify_melody(audio_bytes, mime_type) -> dict` — async entry point; delegates the blocking SDK call to `asyncio.to_thread`.
- `_call_gemini_sync(audio_bytes, mime_type)` — constructs a `genai.Client`, sends audio inline via `types.Part.from_bytes`, and returns the raw text response.
- `_parse_response(text)` — strips markdown fences, extracts the first JSON object, raises `ValueError` on parse failure.
- `base_mime(content_type)` — strips codec parameters (`audio/webm;codecs=opus` → `audio/webm`).
- `ALLOWED_MIME_TYPES` — frozenset of accepted audio MIME types checked before upload.
- Returns 503 if `GEMINI_API_KEY` is not configured; propagates Gemini SDK exceptions to the router (logged as 502).

### `services/library_import.py` — Permanent library storage

- Downloads full audio via yt-dlp, embeds ID3 tags + album art (mutagen), moves file to `{MUSIC_PATH}/{Artist}/{Album}/{Track_Title}.mp3`.
- Case-insensitive artist/album directory resolution; writes `album_meta.json` sidecar.
- Updates DB (`source_type = 'local'`, `local_path`); library watcher auto-indexes the file.

### `services/cache_manager.py` — Cache lifecycle

- `enforce_cache_limit()` — deletes oldest files when `CACHE_DIR` exceeds limit (default 5 GB).
- `promote_track_to_cache(remote_id)` — moves temp → persistent cache on 3rd play.

### `services/track_service.py` — Metadata resolution

- `ensure_track_exists(session, track_id)` — resolves by UUID or YouTube video ID; auto-indexes from YouTube if not found.

### `services/track_repair.py` — DB maintenance

- `repair_stale_tracks()` — cleans phantom `is_cached = True` entries where files are missing; removes records indexed from temp dirs.

---

## 6. Configuration reference

All settings live in `backend/app/config.py` and are populated from the `.env` file.

| Variable | Default | Description |
| :------- | :------ | :---------- |
| `APP_PROFILE` | `server` | Run profile: `server` (Docker/Pi) or `standalone` (self-contained desktop app — loopback bind, OS user-data dirs, local auth). See [features-v7.md](features-v7.md). |
| `DATA_DIR` | OS user-data dir | Standalone only: root for DB, library, logs, and the persisted local JWT secret. Blank → `platformdirs` default. |
| `FFMPEG_PATH` | — | Absolute path to ffmpeg; blank resolves from PATH/venv. Standalone bundle points this at its vendored static build. |
| `DOMAIN` | — | Public hostname; used for OAuth redirect URIs and API base URL. Optional in standalone. |
| `JWT_SECRET` | — | Signs access and refresh tokens. |
| `ALGORITHM` | `HS256` | JWT algorithm. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 60 | Access token lifetime. |
| `REFRESH_TOKEN_EXPIRE_DAYS` | 30 | Refresh token lifetime. |
| `ADMIN_EMAILS` | `""` | Comma-separated emails auto-promoted to `admin` role. |
| `STREAM_URL_SIGNING_SECRET` | (JWT_SECRET) | Separate secret for signed stream URLs. |
| `STREAM_URL_TTL_SECONDS` | 600 | Signed stream URL lifetime (10 min). |
| `MUSIC_PATH` | `/app/library` | Permanent library root (Docker volume). |
| `CACHE_DIR` | `/app/cache` | Persistent YouTube cache (Docker volume). |
| `TEMP_DIR` | `/tmp/myspotify_cache` | LRU-evicted temp stream files. |
| `STREAM_LOW_LATENCY` | `True` | Enable `nobuffer + low_delay` ffmpeg flags. |
| `STREAM_PASSTHROUGH` | `True` | Stream-copy instead of transcode. |
| `STREAM_ANALYZEDURATION_US` | 500000 | ffmpeg `-analyzeduration` (µs). |
| `STREAM_PROBESIZE_BYTES` | 500000 | ffmpeg `-probesize` (bytes). |
| `STREAM_TRANSCODE_BITRATE_KBPS` | 128 | Bitrate when stream-copy is not possible. |
| `STREAM_FORCE_LEGACY_SUBPROCESS` | `False` | Emergency switch to subprocess pipeline. |
| `YTDLP_COOKIES_FILE` | — | Optional Netscape `cookies.txt` for blocked IPs. |
| `YTDLP_YOUTUBE_PLAYER_CLIENT` | `tv,web,mweb` | yt-dlp fallback player clients. |
| `YTDLP_RESOLVED_URL_TTL_SEC` | 18000 | In-memory resolver cache TTL (5 hours). |
| `PREFETCH_ENABLED` | `True` | Enable next-track cache warming. |
| `PREFETCH_MAX_CONCURRENT` | 2 | Max simultaneous prefetch tasks. |
| `GROQ_API_KEY` | — | Groq API key; AI shuffle disabled if unset. |
| `GROQ_MODEL` | `llama-3.1-8b-instant` | Groq model for AI shuffle. |
| `GEMINI_API_KEY` | — | Google Gemini API key; hum-to-search disabled if unset. |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model for melody identification. |
| `IDENTIFY_MIN_CONFIDENCE` | `75` | Minimum Gemini confidence (0–100); lower scores return a not-found error. |
| `GOOGLE_CLIENT_ID` | — | Google OAuth client ID. |
| `GOOGLE_CLIENT_SECRET` | — | Google OAuth client secret. |
| `DATABASE_URL` | `sqlite:////app/db/myspotify.db` | SQLModel database URL. |

See `.env.example` and [local-setup.md](local-setup.md) for OAuth-specific setup instructions.

---

## 7. Client implementation guidelines (mobile / third-party)

### Authentication flow

1. Exchange credentials (or Google ID token) for `access_token` + `refresh_token`.
2. Store tokens securely (e.g. `flutter_secure_storage` on mobile; `localStorage` on web as a minimum).
3. On 401, attempt refresh via `POST /auth/refresh`; on failure, redirect to login.

### Streaming flow

1. Call `POST /tracks/stream/grant` with `{"track_id": "..."}` and `Authorization: Bearer <token>`.
2. Set the returned `stream_url` as the audio source — no custom headers needed.
3. Signed URLs expire in 10 minutes; request a new grant for re-plays or after expiry.
4. Allow ≥ 30 s timeout for cold YouTube proxy startup.

### AI Shuffle flow

1. Collect context track IDs (current track + queue, or recent `PlayHistory`).
2. `POST /tracks/ai-shuffle` with body `{"track_ids": ["...", ...]}` (JWT required).
3. Response is a JSON array of `Track` objects — play as a new playlist.
4. Guard against duplicate triggers: use a synchronous `_aiShufflePending` flag (mobile) or debounce (web) because the end-of-queue event may fire multiple times before state updates.

### Hum-to-Search flow

1. Show a recording overlay/modal (10-second countdown + wave animation).
2. Record audio:
   - **Web:** `navigator.mediaDevices.getUserMedia({audio: true})` → `MediaRecorder` (prefers `audio/webm;codecs=opus`).
   - **Flutter:** `AudioRecorder().start(RecordConfig(encoder: AudioEncoder.aacLc, sampleRate: 44100, numChannels: 1), path: path)` → `stop()` returns file path.
3. Build a `FormData` / `MultipartRequest` with field name `audio` and appropriate MIME type.
4. `POST /api/v1/ai/identify` (JWT required). Show a spinner while identifying.
5. On `200`: auto-fill the search bar with `"Artist - Title"` and trigger a search.
6. On error: show a snackbar/toast with the `message` field from the response body.

**Error shape from the backend:**
```json
{ "code": "http_422", "message": "Could not identify the melody", "detail": null }
```

### Offline / library import flow

1. `POST /tracks/{track_id}/save-to-library` triggers the server-side permanent import (background).
2. Immediately also download the signed stream URL to device storage (`getApplicationDocumentsDirectory()/tracks/{id}.mp3`).
3. On subsequent plays, prefer the local file over requesting a new stream grant.

### State management (Flutter)

`AudioPlayerBloc` state fields:

| Field | Type | Description |
| :---- | :--- | :---------- |
| `currentTrack` | `Track?` | Currently loaded track. |
| `queue` | `List<Track>` | Upcoming tracks. |
| `isPlaying` | `bool` | Playback active. |
| `position` | `Duration` | Current playback position. |
| `duration` | `Duration` | Track duration. |
| `playerState` | `PlayerState` | Underlying `just_audio` state. |
| `isAiShuffling` | `bool` | AI shuffle request in flight. |
| `isSavingToLibrary` | `bool` | Library import in flight. |
| `errorMessage` | `String?` | `'login_required'` or error text. |

Key events: `PlayTrackEvent`, `PlayPlaylistEvent`, `PauseTrack`, `ResumeTrack`, `SkipNextEvent`, `SkipPreviousEvent`, `SeekTrackEvent`, `UpdateTrackLikedStatus`, `TriggerAiShuffleEvent`, `SaveTrackToLibraryEvent`.

`PlayPlaylistEvent` handles per-track URL fetch failures gracefully: tracks that fail URL resolution are dropped from the playlist rather than aborting playback.

### Media controls

- Implement **Media Session** (web) or native equivalents (Android `MediaSession` / iOS `MPNowPlayingInfoCenter`) for lock-screen and OS integration.
- `just_audio` + `audio_service` provide this automatically on Flutter; ensure the `MyAudioHandler` is registered at app startup.

### Design language

- Dark "glass" aesthetic; Lucide icons for parity with the web dashboard.
- Touch targets ≥ 44 × 44 pt on mobile.

---

## 8. Deployment note (static UI)

The dashboard JavaScript and HTML ship **inside the backend image**. The `backend/app` directory is also bind-mounted as a Docker volume (`./backend/app:/app/app`), so code changes are reflected on disk immediately — but the running `uvicorn` process must be **restarted** to pick up new Python modules and routes:

```bash
docker compose restart backend
```

After changing `backend/app/static/*`, bump the `?v=` cache-buster on `<script>` / `<link>` tags in `index.html` so browsers fetch updated assets. A full image rebuild is only needed when changing `requirements.txt` or the Dockerfile:

```bash
docker compose build backend && docker compose up -d backend
```

See [docker.md](docker.md) for full Compose and Pi/reverse-proxy instructions.

---

## 9. Related documents

- [docker.md](docker.md) — Compose, rebuild, troubleshooting on Pi / reverse-proxy setup.
- [local-setup.md](local-setup.md) — Local dev, OAuth redirect URLs, environment variables.
- [requirements.md](requirements.md) — Product requirements (may overlap this spec).
- [features-v3.md](features-v3.md) — Fast YouTube playback: resolver + stream-copy + prefetch.
- [features-v4.md](features-v4.md) — Hover-prefetch, phased timing logs, resolver hardening.
- [features-v5.md](features-v5.md) — Permanent library import + Groq LLM AI shuffle.
- [features-v6.md](features-v6.md) — Hum-to-Search: Gemini multimodal melody identification.
- [features-v7.md](features-v7.md) — Standalone Edition: self-contained desktop/mobile app (no domain or tunnel).
