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
- **Redirect URI:** `https://api.e-music.win/auth/callback`
- **Security:** Use JWT for session management.

## 5. Backend Requirements (FastAPI)
- **Consolidated Search:** Query local SQLite metadata and YouTube Music API simultaneously.
- **Streaming Proxy:** Stream YouTube audio via `yt-dlp` while caching the file to `/share/e-music/cache` on the fly.
- **Metadata:** Use `FFmpeg` to read/write tags for local and cached files.

## 6. Mobile & Cross-Platform Goals
- **Framework:** Flutter (Recommended for Android + future iOS/Web support).
- **Features:** Background playback, media notification controls, and offline metadata sync.

## 7. Immediate Task for Agent
1. Generate a `docker-compose.yml` file including `backend`, `db` (SQLite), and `tunnel` (cloudflared).
2. Generate a `.env` template for all credentials.
3. Provide the initial FastAPI `main.py` structure with Google SSO logic and basic library scanning.