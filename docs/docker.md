# Project Specification: MySpotify Home Server (v3.0 - Final)

## 1. Project Overview
Build a self-hosted music streaming ecosystem for Raspberry Pi 5 (Ubuntu). The system must consolidate local MP3 files with external streaming (YouTube) into a unified library with personal playlists and smart caching.

## 2. Infrastructure & Networking
- **Hardware:** Raspberry Pi 5 with internal SSD.
- **Domain:** `e-music.win`
- **Connectivity:** Cloudflare Tunnel (Connector: `cloudflared` in Docker).
- **Public API:** `https://api.e-music.win`
- **Cloudflare Tunnel Token:** .env file, variable CLOUDFLARE_TUNNEL_TOKEN

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

- **One service (backend, Caddy proxy, tunnel):**  
  `docker compose logs --tail=80 backend`  
  `docker compose logs --tail=80 caddy`  
  `docker compose logs --tail=80 tunnel`

- **Timestamped lines:**  
  `docker compose logs -f -t tunnel`

### Lifecycle

- **Start in background:**  
  `docker compose up -d`

- **Recreate containers after `.env` or image changes:**  
  `docker compose up -d --force-recreate`

- **Rebuild backend image and start:**  
  `docker compose build --pull backend`  
  `docker compose up -d backend`

- **Stop:**  
  `docker compose stop`

- **Stop and remove containers (not volumes):**  
  `docker compose down`

### Networking and names

- **List Compose networks (find `*_myspotify-network`):**  
  `docker network ls | grep myspotify`

- **Inspect a network (substitute real name from `ls`):**  
  `docker network inspect e-music_myspotify-network`

- **Reach Caddy from another container on the same network (diagnostics):**  
  `docker run --rm --network e-music_myspotify-network curlimages/curl curl -sS -i -H "Host: e-music.win" http://caddy:80/health`

### One-off commands inside a container

- **Shell in backend (image must include a shell):**  
  `docker compose exec backend sh`  
  or `docker compose exec backend bash` if available.

- **Note:** The `cloudflared` image often has no shell; test with `curl` from a throwaway container on the same network (see above) instead of `docker compose exec tunnel sh`.

### Disk and cleanup

- **Docker disk usage:**  
  `docker system df`

- **Prune unused images (frees space; use with care):**  
  `docker image prune -f`

### Quick local health checks (on the host)

- **Through Caddy on port 80 (use the real browser `Host`):**  
  `curl -sS -i -H "Host: e-music.win" http://127.0.0.1/health`

- **Inside backend (uvicorn):**  
  `docker compose exec backend curl -sS -i http://127.0.0.1:8000/health`

### Version

- **Compose plugin:**  
  `docker compose version`

- **Docker Engine:**  
  `docker version`