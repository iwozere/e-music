# 🎵 MySpotify

A self-hosted, full-stack music ecosystem that bridges your local library with the vast universe of YouTube Music.

![MySpotify Dashboard](static/assets/dashboard_preview.png)

## 🚀 Overview

MySpotify is a high-performance, self-hosted music sanctuary. It eliminates subscription costs by combining a **FastAPI** backend with a lightweight, responsive **Vanilla JS** frontend. Designed to run on a **Raspberry Pi 5**, it can sit behind any HTTPS reverse proxy or tunnel (for example Cloudflare Tunnel in a separate **pi-infra** stack) and features a hybrid Android/Web architecture.

## ✨ Key Features

- **Unified Search**: Seamlessly search local files and YouTube Music in a single view.
- **Smart LRU Caching**: YouTube streams are automatically cached to your SSD after 3 plays for offline efficiency.
- **OS Integration**: Full support for **Media Session API**, enabling lock-screen controls and system metadata synchronization.
- **AI Radio Mode**: When the queue ends, Groq LLM (Llama 3.1) automatically curates 10 contextual track suggestions resolved via YouTube Music.
- **Hum-to-Search**: Record 10 seconds of humming or singing; Gemini AI identifies the song and auto-fills the search bar (web + Flutter mobile).
- **Permanent Library Import**: Save any YouTube track to your local library with embedded ID3 tags, album art, and offline mobile playback.
- **Self-Healing Indexer**: Background service that monitors your `/library` folder and updates the DB in real-time.

## 🛠 Tech Stack

### Backend
- **Framework**: FastAPI (Python)
- **Database**: SQLModel + SQLite
- **Edge / TLS**: Not bundled here; use your own reverse proxy or tunnel (e.g. Caddy + `cloudflared` in **pi-infra**), or expose port `8000` directly for LAN use
- **Authentication**: Google OAuth2 (Redirect Mode) & JWT
- **AI Services**: Groq API (AI radio shuffle) · Google Gemini (hum-to-search melody identification)

### Frontend & Mobile
- **Web**: Vanilla JavaScript (`api.js`, `player.js`, `ui.js`) with CSS Glassmorphism; served by the backend
- **Flutter**: Native mobile app (`/mobile`) — BLoC state management, `just_audio`, offline playback, hum-to-search overlay
- **Icons**: Lucide Icons

## 📂 Project Structure

- `/backend`: FastAPI source, models, routers, and background services.
- `/backend/app/static`: Web dashboard (HTML/JS/CSS).
- `/mobile`: Flutter app (Android + iOS).
- `docker-compose.yml`: Backend and DB init; optional external **`infra-net`** so a reverse proxy in **pi-infra** can reach `backend:8000`.

## 🚦 Getting Started

### Backend Deployment (Docker & RPi)
1. Ensure your local library is mounted to `/app/library`.
2. Configure your `.env` with `GOOGLE_CLIENT_ID`, `DOMAIN`, and optionally `GROQ_API_KEY` / `GEMINI_API_KEY`.
3. Register **Authorized JavaScript origins** and **Authorized redirect URIs** in Google Cloud ([docs/local-setup.md](docs/local-setup.md), §6).
4. Run `docker compose up -d --build`.

### Flutter Mobile Build
1. Install Flutter SDK and run `flutter pub get` in `/mobile`.
2. Grant microphone permission (required for hum-to-search) — declared in `AndroidManifest.xml` and `Info.plist`.
3. Set the backend URL via the app settings screen, then build and run.

## 🔍 Maintenance & Monitoring

### Real-time Logs
```bash
docker compose logs -f backend
```