# Technical Specification: MySpotify Home Server & Mobile App

## 1. Project Overview

**MySpotify** is a self-hosted music ecosystem designed for Raspberry Pi 5 (Ubuntu). It consolidates a local MP3 library (stored on SSD) with external streaming services (YouTube/SoundCloud) into a single, unified interface.

### Key Objectives:

* **Zero Cost:** No paid subscriptions or API fees.
* **Hybrid Library:** Unified search and playlists for local files and streams.
* **Smart Caching:** Automatic background downloading of streamed tracks to local SSD.
* **Cross-Platform:** Android app and Web interface with future iOS compatibility.

---

## 2. System Architecture

The system follows a Client-Server model optimized for low latency on a local network.

* **Server (Raspberry Pi 5):**
* **OS:** Ubuntu Server.
* **Runtime:** Docker Compose.
* **Backend:** Python (FastAPI) for high-performance asynchronous I/O.
* **Database:** SQLite (WAL mode) for metadata and playlist storage.
* **Audio Processor:** `yt-dlp` for streaming/caching, `FFmpeg` for metadata extraction.


* **Client (Android & Web):**
* **Framework:** Flutter (Recommended for high-performance audio and easy iOS porting).
* **State Management:** Bloc or Provider.



---

## 3. Database Schema (SQLite)

```sql
CREATE TABLE tracks (
    id TEXT PRIMARY KEY,           -- Internal UUID
    title TEXT NOT NULL,
    artist TEXT,
    album TEXT,
    source_type TEXT,              -- 'local', 'youtube', 'soundcloud'
    remote_id TEXT,                -- YouTube Video ID or URL
    local_path TEXT,               -- Path on SSD if cached/local
    is_cached BOOLEAN DEFAULT 0,
    duration INTEGER,              -- In seconds
    added_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE playlists (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    is_offline BOOLEAN DEFAULT 0   -- If true, force-cache all tracks
);

CREATE TABLE playlist_tracks (
    playlist_id TEXT,
    track_id TEXT,
    position INTEGER,
    FOREIGN KEY(playlist_id) REFERENCES playlists(id),
    FOREIGN KEY(track_id) REFERENCES tracks(id)
);

```

---

## 4. Feature Requirements

### A. Unified Search (Federated)

* The backend must query the local SQLite DB and the `ytmusicapi` concurrently.
* Merge results into a standardized JSON response.

### B. Transparent Caching Proxy

* When a remote track is played, the server provides a proxy URL: `http://pi-ip:8000/stream/{track_id}`.
* The server checks for the file on SSD. If missing, it uses `yt-dlp` to stream the audio to the client while simultaneously saving it to the cache directory.

### C. Android Mobile Client

* **Background Playback:** Audio must continue when the screen is off.
* **Mini-player:** Global controls for play/pause/skip.
* **Sync Logic:** Local metadata cache to allow browsing when disconnected from the home Wi-Fi.

---

## 5. Cross-Platform & Future Compatibility

> **Architecture Note:** All core business logic (authentication, API calls, data parsing) must be kept in a separate "Service" layer. Use abstract classes for the Audio Player to ensure that switching from Android-specific players to iOS/Web players requires zero changes to the UI code.

---

## 6. Implementation Roadmap (Phase 1)

1. **Backend Setup:** Initialize FastAPI with Docker and mount the SSD volume.
2. **Indexing:** Create a script to scan `/mnt/ssd/music` and populate the `tracks` table.
3. **Streamer:** Implement the `yt-dlp` streaming bridge.
4. **Flutter App:** Basic UI with a list of tracks and a simple playback bar.

---

## 1. Updated Database Schema (Multi-User)

We need to add a `users` table and link tracks/playlists to specific owners.

```sql
-- User management
CREATE TABLE users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    hashed_password TEXT NOT NULL,
    role TEXT DEFAULT 'user', -- 'admin' for managing the Pi, 'user' for family
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Personalization: Likes and History
CREATE TABLE user_activity (
    user_id TEXT,
    track_id TEXT,
    play_count INTEGER DEFAULT 0,
    is_liked BOOLEAN DEFAULT 0,
    last_played DATETIME,
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(track_id) REFERENCES tracks(id)
);

-- Update Playlists to be private by default
ALTER TABLE playlists ADD COLUMN owner_id TEXT;
ALTER TABLE playlists ADD COLUMN is_public BOOLEAN DEFAULT 0;

```

---

## 2. Authentication Strategy for Antigravity IDE

For the IDE to generate this correctly, we will use the **FastAPI OAuth2 Password Flow**.

* **Registration:** A simple endpoint where you create accounts for family members.
* **Login:** The Android app sends credentials; the Pi returns a **JWT Token**.
* **Secure Storage:** The Android app (Flutter) will use `flutter_secure_storage` to keep this token safe. It’s like a "digital key" that the app shows the server every time you request a song.

---

## 3. Tech Stack Recommendations for Multi-User

| Feature | Tool / Library | Why? |
| --- | --- | --- |
| **Password Hashing** | `Passlib` (bcrypt) | Never store passwords in plain text, even on a home server. |
| **Token Handling** | `PyJWT` | Standard, secure, and very fast on Pi 5. |
| **Android Security** | `Biometric (Fingerprint)` | Flutter allows easy integration so only you can open your player. |
| **User Isolation** | `Scoping` | Every DB query will now include `WHERE owner_id = current_user_id`. |

---

## 4. Personalized "Consolidated" Search

With multiple users, the search gets "smarter":

1. **Global Search:** Find the song on the SSD or YouTube.
2. **User Context:** If the song is already in your "Liked Songs", the UI shows a heart icon immediately.
3. **Recommendations:** You can later add a "Discovery" tab based on the `user_activity` table (e.g., "Songs you played the most this week").

---

# MySpotify: Technical Specification Addendum (v2.2)

## 1. Network Access & Connectivity

**Problem:** The Raspberry Pi 5 is behind Double NAT (two routers) with no public IP.
**Solution:** **Cloudflare Tunnel (Argo Tunnel)**.

### Implementation Requirements:

* **Infrastructure:** Run a `cloudflared` Docker container on the Raspberry Pi.
* **Security:** Cloudflare provides the SSL termination (HTTPS). The mobile app will connect to a custom domain (e.g., `https://music.yourdomain.com`).
* **App Logic:** The Android/Web client must support a configurable "Base URL" to point to the Cloudflare endpoint.

## 2. Persistent Storage & Disk Management

**Strategy:** **Permanent Cache (No Auto-Deletion).**

### Implementation Requirements:

* **Storage Path:** External SSD mounted at `/mnt/music_data`.
* **Directory Structure:**
* `/mnt/music_data/library/`: Manually uploaded MP3s.
* `/mnt/music_data/cache/`: Files downloaded via the streaming bridge.


* **Logic:**
* The system shall **not** implement automated cleanup.
* The `is_cached` flag in the database must be permanent until a user manually deletes a track.
* **Health Monitor:** The Backend API must expose an endpoint `/system/storage` that returns used/available space on the SSD for the UI to display.



## 3. Revised Authentication & User Roles

**Strategy:** **Open Registration with Data Isolation.**

### Implementation Requirements:

* **Sign-up Flow:** Anyone can sign up via Google OAuth2 or Email/Password.
* **Data Scoping:**
* **Public Assets:** The `library/` folder (local MP3s) is shared and searchable by all users.
* **Private Assets:** Playlists, "Liked Songs," and personal listening history are strictly scoped to the `user_id`.
* **Cache Ownership:** If User A streams a song, it caches to the SSD. If User B searches for the same song, the system should recognize it is already cached and serve it locally, regardless of who triggered the initial download.


* **Admin Privileges:** The first created user (or a specific flag in `.env`) has access to the `/admin` dashboard to monitor storage and manage users.

## 4. Technical Stack Summary for Agent

* **Tunneling:** `cloudflared` (sidecar container).
* **Backend:** FastAPI + SQLAlchemy (SQLite).
* **Proxy:** Caddy (as an internal reverse proxy for local Docker networking).
* **Mobile Auth:** `AppAuth-Android` or Flutter `google_sign_in` for OAuth2 flow.


Отличное решение. Использование сетевой папки `/share/e-music` удобно тем, что вы сможете просто «накидывать» новые MP3 со своего основного компьютера, и они тут же будут появляться в библиотеке MySpotify.

Так как это ваш системный SSD, папка `/share`, скорее всего, уже примонтирована. Нам нужно только убедиться, что Docker-контейнеры и бэкенд смогут туда записывать данные.

Вот как мы скорректируем инструкции для вашего агента **Antigravity**:

### 1. Подготовка структуры папок

Выполните эти команды на Raspberry Pi, чтобы создать нужную структуру внутри вашей сетевой папки:

```bash
# Создаем структуру внутри вашей сетевой папки
mkdir -p /share/e-music/library
mkdir -p /share/e-music/cache
mkdir -p /share/e-music/db

# Убедимся, что права доступа позволяют запись
chmod -R 775 /share/e-music

```

**Update for the Agent on Storage & Paths:**
1. **Root Directory:** All project data will be stored in `/share/e-music`. This is a directory on the internal system SSD, which is also shared across the local network.
2. **Sub-directories for Docker Volumes:**
* **Local Library:** `/share/e-music/library` (Where I will drop my MP3 files).
* **Persistent Cache:** `/share/e-music/cache` (Where `yt-dlp` will save streamed tracks).
* **Database:** `/share/e-music/db` (For the SQLite database file).

3. **Permissions:** The service must run with appropriate UID/GID to ensure it can read/write to this shared directory.



---

## 5.1 Library Watcher & Background Tasks
- **Service:** Implement a background observer (using `watchdog` or `apscheduler`).
- **Functionality:** - Automatically scan `/share/e-music/library` for new files or changes.
    - Extract metadata (Artist, Album, Title, Year, Cover Art) using `mutagen` or `tinytag`.
    - Update the SQLite database incrementally without freezing the main API.
- **Organization:** Maintain the hierarchy `Artist/Album/Track.mp3`. If metadata is missing, fallback to directory names for identification.

---

## 8. Web Interface Requirements
- **Feature:** Build a responsive Web Dashboard accessible via browser at `https://e-music.win`.
- **Tech Stack:** Simple Single Page Application (SPA).
- **Functionality:**
    - Authentication via the same Google OAuth2 flow.
    - Music player with play/pause, seek, and volume controls (HTML5 Audio API).
    - Grid/List view of the library and playlists.
    - Unified search bar (Local + YouTube).
    - **Share Functionality (v2.3):**
        - **Native Sharing:** Mobile users can share tracks/playlists via system share sheet.
        - **Clipboard:** Desktop users can copy unique share URLs to clipboard.
        - **Deep Linking:** URLs with `?track=ID` automatically start playback on load.
- **Backend Integration:** The FastAPI backend should serve the static frontend files and provide `/stream/{track_id}` endpoints that support HTTP Range requests (crucial for seeking in the browser player).