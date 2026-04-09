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
| **Media** | `yt-dlp` for YouTube audio; local library indexing and file watching on startup |

**API base path:** All JSON endpoints are under **`/api/v1`**. The reference web client uses `window.location.origin + '/api/v1'`.

**Health (unversioned):** `GET /health` returns `{"status": "healthy"}`.

---

## 2. Core features

### 2.1 Unified search & discovery

- **Logic:** Combines local SQLite results with YouTube Music search; merges duplicates when a YouTube `remote_id` matches an indexed track.
- **Pagination:** `offset` and `limit` (default page size in the web UI is 20).
- **Source indicators (web):** Local tracks show a “hard drive” style icon; YouTube-sourced rows show a “cloud” style icon.
- **Cached badge:** YouTube-origin tracks that are stored on server disk (`is_cached`) can be labeled as cached in the UI.

**Search route:** `GET /api/v1/tracks/search?q=...&offset=&limit=`.

### 2.2 Streaming & caching

- **Proxy streaming:** YouTube audio is proxied through the backend (avoids browser CORS and hides client complexity).
- **Signed stream URLs:** Playback does **not** use a long-lived `Authorization` header on the `<audio>` element. Clients must:
  1. `POST /api/v1/tracks/stream/grant` (JWT required) with body `{"track_id": "<id>"}`.
  2. Use the returned `stream_url` (short-lived `exp` / `sig` / `uid` query parameters) as the audio source.
- **Atomic caching:** Downloads use temporary files and promote to final paths when complete where applicable.
- **Play-count promotion:** On **`POST /api/v1/tracks/{track_id}/play`**, after the **third** completed play for a YouTube-backed track (`remote_id` set), the backend may promote it into persistent cache and set `is_cached`.
- **Seeking:** Cached/local files support HTTP Range requests; live/proxy paths use chunked streaming as implemented in the streamer.

### 2.3 Playback logic (web dashboard)

- **Queue:** “Add to Queue” and “Play Next” mutate an in-memory queue; the player advances the queue, then continues within `currentTracksContext` (wraps to the next item in the visible grid/list).
- **Play All / Play Random:** Available for playlist and liked-song contexts in the web UI header.
- **Radio / related tracks:** `GET /api/v1/tracks/{track_id}/related` returns related YouTube Music–backed suggestions (intended for autoplay / radio-style clients). The bundled web player does **not** automatically call this when the queue ends; mobile or future clients can wire it in.

### 2.4 Organization

- **Liked songs:** Per-user likes via `UserActivity.is_liked` and `GET /api/v1/tracks/liked`.
- **Playlists:** Owner-scoped; tracks ordered by `position` in `PlaylistTrack`.
- **Recently added:** `GET /api/v1/tracks/recent` — tracks ordered by `added_at` (indexer or cache).

---

## 3. Backend API specification

### Authentication

- **Mechanisms:** Username/password (`POST /api/v1/auth/register`, `POST /api/v1/auth/token`), Google OAuth (see [local-setup.md](local-setup.md)), and **refresh tokens** (`POST /api/v1/auth/refresh`).
- **JWT:** Send `Authorization: Bearer <access_token>` on API calls (except stream **GET**, which uses the signed URL from **stream/grant**).

### Configuration

| Endpoint | Method | Description |
| :------- | :----- | :---------- |
| `/api/v1/config` | GET | Public settings for clients (e.g. Google client id). No auth. |

### Tracks & playback

| Endpoint | Method | Description |
| :------- | :----- | :---------- |
| `/api/v1/tracks/search` | GET | Unified search (`q`, `offset`, `limit`). |
| `/api/v1/tracks/popular` | GET | Tracks ranked by aggregated play counts (`offset`, `limit`). |
| `/api/v1/tracks/recent` | GET | Recently added (`offset`, `limit`). |
| `/api/v1/tracks/liked` | GET | Current user’s liked tracks. |
| `/api/v1/tracks/{track_id}` | GET | Single track metadata. |
| `/api/v1/tracks/{track_id}/like` | POST | Toggle like; query param `is_liked` (see web `api.js`). |
| `/api/v1/tracks/{track_id}/play` | POST | Record play; increments count; may trigger cache promotion. |
| `/api/v1/tracks/{track_id}/related` | GET | Related tracks (YouTube-backed; for radio/autoplay UIs). |
| `/api/v1/tracks/stream/grant` | POST | Returns signed `stream_url` for the given `track_id`. |
| `/api/v1/tracks/stream/{track_id}` | GET | Audio bytes; **requires** valid `exp`, `sig`, `uid` from grant. |

### Playlists

| Endpoint | Method | Description |
| :------- | :----- | :---------- |
| `/api/v1/playlists` | GET | List current user’s playlists. |
| `/api/v1/playlists` | POST | Create playlist (`application/x-www-form-urlencoded`, `name`). |
| `/api/v1/playlists/{playlist_id}` | DELETE | Delete playlist. |
| `/api/v1/playlists/{playlist_id}/tracks` | GET | List tracks (ordered). |
| `/api/v1/playlists/{playlist_id}/tracks` | POST | Add track (`track_id` in form body). |
| `/api/v1/playlists/{playlist_id}/tracks/{track_id}` | DELETE | Remove track from playlist. |

### System (admin only)

| Endpoint | Method | Description |
| :------- | :----- | :---------- |
| `/api/v1/system/index` | POST | Trigger re-index in the background. |
| `/api/v1/system/storage` | GET | Disk usage summary inside the container. |

Full request/response shapes and auth requirements are defined in the FastAPI routers under `backend/app/routers/`.

---

## 4. Data models (SQLModel)

### `User`

- `id`, `username`, `email`, optional `hashed_password`, `role`, `created_at`
- Relationships: `activities`, `playlists`

### `Track`

- `id` (string PK), `title`, `artist`, `album`, `thumbnail`, `duration`
- `source_type`: `'local'` or `'youtube'`
- `remote_id`: YouTube video id when applicable (unique when set)
- `local_path`: server filesystem path when file exists
- `is_cached`: persisted on SSD / cache dir
- `added_at`: used for “Recent” ordering

### `UserActivity` (composite PK: `user_id`, `track_id`)

- `play_count`, `is_liked`, `last_played`

### `Playlist` / `PlaylistTrack`

- `Playlist`: `id`, `name`, `owner_id`, `is_offline`, `is_public`
- `PlaylistTrack`: `playlist_id`, `track_id`, `position`

### `RefreshToken`

- Opaque refresh tokens (hashed at rest), tied to `user_id`, expiry, etc.

---

## 5. Client implementation guidelines (mobile / third-party)

### Media controls

- Implement **Media Session** (web) or native equivalents (e.g. iOS `MPNowPlayingInfoCenter`) for lock-screen and OS integration.
- Handle `play`, `pause`, `next`, `previous`, and **seek** where the stream supports ranges.

### State management (Flutter)

- **AudioPlayerBloc:** `currentTrack`, `isPlaying`, `queue`, `playbackPosition`.
- **Search / lists:** `query`, `results`, pagination (`offset` / `limit`), and abortable fetches where applicable.

### Streaming on iOS and strict clients

- Prefer the **grant + signed URL** flow so `AVPlayer` does not need custom JWT headers on the audio request.
- Allow sufficient timeouts for cold YouTube proxy startup (on the order of tens of seconds).
- Ensure responses support range requests where seeking is required.

### Design language (web reference)

- Dark “glass” aesthetic; Lucide icons for parity with the dashboard.
- Touch targets at least ~44×44 pt on mobile.

---

## 6. Deployment note (static UI)

The dashboard JavaScript and HTML ship **inside the backend image**. After changing `backend/app/static/*`, rebuild the backend image and recreate the container; bump `?v=` on script/link tags in `index.html` so browsers fetch new assets. See [docker.md](docker.md).

---

## 7. Related documents

- [docker.md](docker.md) — Compose, rebuild, troubleshooting on Pi / tunnel setup.
- [local-setup.md](local-setup.md) — Local dev, OAuth redirect URLs, environment variables.
- [requirements.md](requirements.md) — Product requirements (may overlap this spec).
