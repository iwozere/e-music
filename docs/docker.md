# Project Specification: MySpotify Home Server (v3.0 - Final)

## 1. Project Overview
Build a self-hosted music streaming ecosystem for Raspberry Pi 5 (Ubuntu). The system must consolidate local MP3 files with external streaming (YouTube) into a unified library with personal playlists and smart caching.

## 2. Infrastructure & Networking
- **Hardware:** Raspberry Pi 5 with internal SSD.
- **Domain / HTTPS:** Your public hostname (e.g. `e-music.win`) is configured at the edge (DNS, TLS, tunnel). This repo does **not** run `cloudflared` or Caddy; those typically live in a separate stack such as **pi-infra**.
- **This Compose file:** Defines the **backend** and **db-init** only. Optional external network **`infra-net`** lets a reverse proxy on that network forward to **`backend:8000`** by service name.
- **App configuration:** Use **`PUBLIC_API_BASE_URL`** in `.env` when clients reach the API on a public `https://…` host while the app sees an internal `Host` header. The backend does **not** read tunnel tokens (`CLOUDFLARE_TUNNEL_TOKEN` is not an application setting).

### Optional `.env` (proxy + YouTube)

- **`PUBLIC_API_BASE_URL`**: Public `https://…` origin of the API for signed stream URLs when the app is reached via an internal URL behind a reverse proxy.
- **`YTDLP_COOKIES_FILE`**, **`YTDLP_YOUTUBE_PLAYER_CLIENT`**, **`YTDLP_EXTRA_ARGS`**: Tune server-side YouTube extraction (see `backend/app/config.py` and `app/services/streamer.py`).

## 3. Storage & Disk Management
- **Root Directory:** `/share/e-music` (On system SSD, accessible via local network).
- **Directory Structure:**
    - `/share/e-music/library`: Source for local MP3 files.
    - `/share/e-music/cache`: Permanent storage for streamed tracks (No auto-cleanup).
    - `/share/e-music/db`: Storage for SQLite database.
- **Requirement:** Ensure Docker volumes are mapped correctly to these persistent paths.

## 4. Authentication (Google OAuth2)
- **Status:** Open registration for family members.
- **Client ID:** .env file, variable GOOGLE_CLIENT_ID
- **Client Secret:** .env file, variable GOOGLE_CLIENT_SECRET
- **Redirect URI:** Match `.env` `GOOGLE_REDIRECT_URI`, e.g. `https://api.e-music.win/api/v1/auth/callback` (see [local-setup.md](local-setup.md), Google OAuth section).
- **Security:** Use JWT for session management.

## 5. Backend Requirements (FastAPI)
- **Consolidated Search:** Query local SQLite metadata and YouTube Music API simultaneously.
- **Streaming Proxy:** Stream YouTube audio via `yt-dlp` while caching the file to `/share/e-music/cache` on the fly.
- **Metadata:** Use `FFmpeg` to read/write tags for local and cached files.

## 6. Mobile & Cross-Platform Goals
- **Framework:** Flutter (Recommended for Android + future iOS/Web support).
- **Features:** Background playback, media notification controls, and offline metadata sync.

## 7. Docker Compose — status, logs, and troubleshooting

Run these from the project root where `docker-compose.yml` lives (for example `/opt/apps/e-music`). Compose V2 uses `docker compose` (space); older installs may use `docker-compose` (hyphen).

### Status and processes

- **Service summary (intended state, ports, health):**  
  `docker compose ps`

- **All running containers (any project):**  
  `docker ps`  
  `docker ps -a` (includes stopped)

- **Live resource use (CPU, memory, I/O):**  
  `docker stats`  
  `docker stats --no-stream` (one snapshot)

### Logs

- **Tail all services:**  
  `docker compose logs --tail=100`

- **Follow logs (Ctrl+C to stop):**  
  `docker compose logs -f --tail=50`

- **Backend only:**  
  `docker compose logs --tail=80 backend`

- **Timestamped lines:**  
  `docker compose logs -f -t backend`

### Lifecycle

- **Start in background:**  
  `docker compose up -d`

- **Recreate containers after `.env` or image changes:**  
  `docker compose up -d --force-recreate`

- **Rebuild backend image and start:**  
  `docker compose build --pull backend`  
  `docker compose up -d backend`

- **After changing web UI files** (`backend/app/static/*.js`, `index.html`, `style.css`, etc.):  
  Those assets are **baked into the backend image** at build time (see `backend/Dockerfile`). **Restarting the Pi or container alone is not enough** if the image still contains old files.

  1. Bump the `?v=…` query strings in `backend/app/static/index.html` whenever you change static assets so browsers do not keep an old cached `main.js` / `ui.js`.
  2. Rebuild and recreate the backend container:
     ```bash
     docker compose build --pull backend
     docker compose up -d --force-recreate backend
     ```
  3. **Verify** the running image serves the new bundle (example: search for a string you added, or the current app version in `main.js`):
     ```bash
     docker compose exec backend grep -n paginatedViews /app/app/static/main.js
     ```
     (Adjust `/app/app/static` if your image layout differs; use `docker compose exec backend sh` and `find` if unsure.)

- **Stop:**  
  `docker compose stop`

- **Stop and remove containers (not volumes):**  
  `docker compose down`

### Networking and names

- **List Compose networks (find `*_myspotify-network`):**  
  `docker network ls | grep myspotify`

- **Inspect a network (substitute real name from `ls`):**  
  `docker network inspect e-music_myspotify-network`

### One-off commands inside a container

- **Shell in backend (image must include a shell):**  
  `docker compose exec backend sh`  
  or `docker compose exec backend bash` if available.

- **Tunnel / edge:** If `cloudflared` runs in **pi-infra**, use that project’s docs to inspect or debug it; this compose stack has no `tunnel` service.

### Disk and cleanup

- **Docker disk usage:**  
  `docker system df`

- **Prune unused images (frees space; use with care):**  
  `docker image prune -f`

### Quick local health checks (on the host)

- **Backend directly (uvicorn):**  
  `docker compose exec backend curl -sS -i http://127.0.0.1:8000/health`  
  (Public HTTP routing is configured in the **pi-infra** reverse proxy, not in this compose file.)

### Version

- **Compose plugin:**  
  `docker compose version`

- **Docker Engine:**  
  `docker version`