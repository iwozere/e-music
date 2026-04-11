# 🎵 MySpotify

A self-hosted, full-stack music ecosystem that bridges your local library with the vast universe of YouTube Music.

![MySpotify Dashboard](static/assets/dashboard_preview.png) ## 🚀 Overview

MySpotify is a high-performance, self-hosted music sanctuary. It eliminates subscription costs by combining a **FastAPI** backend with a lightweight, responsive **Vanilla JS** frontend. Designed to run on a **Raspberry Pi 5**, it leverages Cloudflare Tunnels for secure remote access and features a hybrid Android/Web architecture.

## ✨ Key Features

- **Unified Search**: Seamlessly search local files and YouTube Music in a single view.
- **Smart LRU Caching**: YouTube streams are automatically cached to your SSD after 3 plays for offline efficiency.
- **OS Integration**: Full support for **Media Session API**, enabling lock-screen controls and system metadata synchronization.
- **Infinite Discovery**: "Radio Mode" uses YouTube's related tracks API to keep the music playing after your queue ends.
- **Cross-Platform Ready**: Single-page architecture optimized for **Android WebView** and future **iOS** deployment.
- **Self-Healing Indexer**: Background service that monitors your `/library` folder and updates the DB in real-time.

## 🛠 Tech Stack

### Backend
- **Framework**: FastAPI (Python)
- **Database**: SQLModel + SQLite
- **Proxy/Web**: Reverse proxy (Caddy runs in the **pi-infra** project) & Cloudflare Tunnel
- **Authentication**: Google OAuth2 (Redirect Mode) & JWT

### Frontend & Mobile
- **Core**: Vanilla JavaScript (Modular Architecture: `api.js`, `player.js`, `ui.js`)
- **UI**: Modern CSS3 with Glassmorphism and CSS Grid
- **Android**: Native WebView wrapper with Hardware Media Key support
- **Icons**: Lucide Icons

## 📂 Project Structure

- `/backend`: FastAPI source, models, and background services.
- `/static`: Modular frontend (HTML/JS/CSS).
- `/mobile/android`: Android Studio project (WebView wrapper).
- `docker-compose.yml`: Backend, DB init, and Cloudflare tunnel (reverse proxy is in **pi-infra**).

## 🚦 Getting Started

### Backend Deployment (Docker & RPi)
1. Ensure your local library is mounted to `/app/library`.
2. Configure your `.env` with `GOOGLE_CLIENT_ID` and `DOMAIN`.
3. Register **Authorized JavaScript origins** and **Authorized redirect URIs** in Google Cloud ([docs/local-setup.md](docs/local-setup.md), §6).
4. Run `docker compose up -d --build`.

### Android Build
1. Open the `/mobile/android` folder in **Android Studio**.
2. Ensure **Gradle Sync** completes using the included wrapper.
3. Build the APK to enjoy a native-like experience with system media controls.

## 🔍 Maintenance & Monitoring

### Real-time Logs
```bash
docker compose logs -f backend