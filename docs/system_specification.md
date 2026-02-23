# MySpotify: Technical Specification & Feature Documentation

This document serves as a consolidated technical reference for the MySpotify ecosystem, intended for developers implementing new clients (e.g., iOS).

## 1. System Architecture OVERVIEW

MySpotify is a self-hosted music ecosystem with a centralized backend and multi-platform clients.

- **Backend**: FastAPI (Python 3.10+) with SQLModel (SQLite).
- **Web Frontend**: Vanilla JavaScript (ES6+), CSS3 with Glassmorphism, Lucide Icons.
- **Mobile**: Flutter (Dart) using BLoC pattern for state management.
- **Media Engine**: `yt-dlp` for YouTube streaming and local file indexing.

---

## 2. Core Features

### 2.1 Unified Search & Discovery
- **Logic**: Searches both the local database (indexed tracks) and YouTube Music concurrently.
- **Deduplication**: Backend automatically merges YouTube results with local records if a matching `remote_id` is found.
- **Pagination**: 20 tracks per page via `offset` and `limit`.
- **Source Indicators**:
    - <i data-lucide="hard-drive"></i> **Local**: Track exists in the permanent music library.
    - <i data-lucide="cloud"></i> **YouTube**: Track is being proxied from YouTube Music.
- **Cached Badge**: YouTube tracks already saved to the server SSD show a "CACHED" status.

### 2.2 Streaming & Caching
- **Proxy Streaming**: All YouTube content is proxied through the backend to avoid CORS issues and client-side complexity. 
- **Atomic Caching**: Streams are written to `.download` files and only renamed to `.mp3` upon 100% completion. This prevents partial/corrupt files.
- **Popularity-Based Promotion**:
    - Tracks played **3 times** are automatically promoted from temporary cache to persistent storage.
    - Persistent tracks are marked as `is_cached=True` in the database.
- **Seeking Support**: Cached tracks support full HTTP Range requests. Live streams use optimized buffers (128KB chunks) for low latency.

### 2.3 Playback Logic
- **Queue Management**: "Play Next" and "Add to Queue" support. 
- **Play All**: Starts playback from the first track in a context (Playlist/Liked Songs) and automatically handles the sequence.
- **Radio Mode**: When the queue ends, the system fetches "Related" tracks from YouTube Music based on the last played song.

### 2.4 Organization
- **Liked Songs**: User-specific hearting system.
- **Playlists**: Custom collections with positional ordering.
- **Recently Added**: A unified view of the latest local additions and recently cached YouTube tracks.

---

## 3. Backend API Specification

### Authentication
- **Method**: Google OAuth2 (OpenID) and JWT tokens.
- **Header**: `Authorization: Bearer <token>`

### Endpoints (v2.8.4)

| Endpoint | Method | Description |
| :------- | :----- | :---------- |
| `/search?q=...&offset=0&limit=20` | GET | Unified search (Local + YT). |
| `/tracks/popular` | GET | Locally stored tracks sorted by global play count. |
| `/tracks/liked` | GET | Current user's liked collection. |
| `/tracks/recent` | GET | Tracks sorted by `added_at` (indexer or cache date). |
| `/stream/{track_id}` | GET | Audio stream. Handles local, cached, or live YT. |
| `/tracks/{track_id}/like` | POST | Toggle like status for a track. |
| `/tracks/{track_id}/play` | POST | Record a play event (increments count, triggers cache). |
| `/playlists` | GET/POST | List or create user playlists. |
| `/playlists/{id}/tracks` | GET/POST | Manage tracks within a playlist (uses `position`). |
| `/tracks/{track_id}/related` | GET | Returns related tracks for Radio Mode. |

---

## 4. Data Models (SQLModel)

### `Track`
- `id` (UUID string, primary key)
- `title`, `artist`, `album`, `thumbnail`, `duration`
- `source_type`: `'local'` or `'youtube'`
- `remote_id`: YouTube video ID (if applicable)
- `local_path`: Absolute path on the server
- `is_cached`: Boolean (True if SSD-stored)
- `added_at`: Timestamp (critical for "Recent" view)

### `UserActivity`
- `user_id`, `track_id`
- `is_liked`: Boolean
- `play_count`: Integer (Threshold of 3 triggers cache promotion)
- `last_played`: Timestamp

---

## 5. Client Implementation Guidelines (for iOS/Mobile)

### Media Controls
- Implement **MediaSession API** (or native iOS `MPNowPlayingInfoCenter`) for lock-screen controls.
- Handle `play`, `pause`, `next`, `previous`, `seek`.

### State Management (BLoC Recommendation)
- **AudioPlayerBloc**: Manage `currentTrack`, `isPlaying`, `queue`, and `playbackPosition`.
- **SearchBloc**: Manage `query`, `results`, and pagination state.

### Design Language
- **Theme**: Obsidian/Glassmorphism (Dark Mode).
- **Icons**: Use [Lucide Icons](https://lucide.dev) for consistency across platforms.
- **Targets**: Ensure touch targets are at least 44x44 points.
