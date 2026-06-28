# Technical Specification: Self-Contained Desktop & Mobile Application ("Standalone Edition")

## 1. Objective

Today MySpotify assumes a **self-hosted server** model: a backend on a Raspberry Pi, a registered `DOMAIN`, Google OAuth redirect URIs, and an HTTPS edge (Cloudflare Tunnel / reverse proxy in `pi-infra`). That is a high barrier — most people who would enjoy a personal Spotify alternative cannot register a domain or stand up a tunnel.

**Goal:** Package MySpotify as a **self-contained application a non-technical user can download and run on their own computer** (Windows / macOS / Linux), with no domain, no tunnel, no reverse proxy, and no mandatory cloud accounts. The user double-clicks an installer, the app opens, they search and play, and their library grows on their own disk over time. A mobile path lets the phone act as a remote for that desktop instance (and, later, run fully on-device).

This is **additive**. The existing server/tunnel deployment stays fully supported; Standalone Edition is a new run profile that reuses the same FastAPI backend and web UI.

### Non-goals
- Replacing the Pi/server deployment (it remains the multi-user, always-on profile).
- Multi-user accounts in standalone mode (standalone is single-user / single-machine).
- Shipping a public hosted service.

---

## 2. Run profiles

Introduce an explicit `APP_PROFILE` setting (config, default `server`) so one codebase serves both worlds:

| Profile | Bind | Auth | Edge / TLS | Storage | Intended user |
| :------ | :--- | :--- | :--------- | :------ | :------------ |
| `server` (today) | `0.0.0.0:8000` | JWT + Google OAuth | external tunnel / proxy | Docker volumes (`/app/...`) | Pi / homelab, multiple devices |
| `standalone` (new) | `127.0.0.1:<port>` | **Local single-user** (auto-login), OAuth optional | none — plain HTTP on loopback | OS user-data dir | Anyone on their own PC |

Selecting `standalone` flips the behavioral differences described below. Everything else (search, streaming, caching, library import, AI features) is shared code.

---

## 3. Packaging & distribution

**Goal:** A single downloadable artifact per OS that bundles the Python backend, the web UI, and the native media tools, and launches a window pointed at the local backend.

### 3.1 Desktop shell

Recommended: **pywebview** (Python-native, ~lightweight, uses the OS WebView — WebView2 on Windows, WKWebView on macOS, WebKitGTK on Linux). It keeps the stack pure-Python (no Node/Electron toolchain) and lets the launcher start uvicorn and open a window pointing at `http://127.0.0.1:<port>` in one process.

- **Fallback option:** **Tauri** (Rust shell, smallest binaries, best auto-update story) if we want a polished native installer and don't mind a second toolchain. Defer unless pywebview proves limiting.
- **Minimum option:** No shell at all — the launcher starts uvicorn and opens the user's default browser to the local URL. Ship this first; it's the cheapest path to "it works."

**Why pywebview over Tauri here:** our "real" backend is Python (FastAPI + yt-dlp + ffmpeg), not the shell's language. In both pywebview and Tauri the shell's only jobs are *window + child-process lifecycle + installer* — it just wraps a localhost web app. Tauri's main value (Rust as the app backend) is therefore unused, while its cost (a second Rust + Node toolchain, which breaks our current "no build step" rule) is fully paid. pywebview keeps the stack pure-Python. The one area Tauri clearly wins is **signed installers + a built-in auto-updater**; adopt Tauri only if/when that becomes the priority.

| Aspect | Browser-open (min) | **pywebview (recommended)** | Tauri (fallback) |
| :----- | :----------------- | :-------------------------- | :--------------- |
| **Added toolchain** | none | none (pure Python) | Rust **+** Node/JS build step |
| **WebView engine** | user's default browser | OS WebView (WebView2 / WKWebView / WebKitGTK) | OS WebView (same engines) |
| **Shell binary size** | 0 | ~small (Python) | ~3–10 MB |
| **App window feel** | a browser tab | native window | native window (most polished) |
| **Installers** | DIY (Inno/dmg/AppImage) | DIY (Inno/dmg/AppImage) | **built-in, signed** |
| **Auto-update** | DIY (GitHub Releases check) | DIY (GitHub Releases check) | **built-in, signature-verified** |
| **Launch Python backend** | spawn uvicorn directly | spawn uvicorn directly | sidecar (first-class) |
| **Fits "no build step" rule** | ✅ | ✅ | ❌ |
| **Main risk** | feels like a browser, not an app | Linux WebKitGTK quirks (audio/MSE) | learning curve + unused Rust core |
| **Best when** | proving the standalone profile fast (phase 3) | shipping a real app window cheaply | signed installers + auto-update are the priority |

### 3.2 Bundling the backend

- Freeze the backend with **PyInstaller** (one-folder build; not one-file, to avoid slow temp-extraction of ffmpeg on every launch).
- A new entrypoint `backend/app/desktop.py`:
  1. Resolve/create the user-data dir (see §5).
  2. Pick a free loopback port (try 8000, else ephemeral) and write it to a runtime file.
  3. Run Alembic migrations against the local SQLite DB.
  4. Start uvicorn programmatically (`uvicorn.run(app, host="127.0.0.1", port=port)`) on a background thread.
  5. Wait for `GET /health` to return healthy, then open the WebView/browser.
  6. On window close, signal uvicorn to shut down and exit cleanly.

### 3.3 Bundling native tools (ffmpeg + yt-dlp)

These are the only hard external dependencies and the biggest reliability risk.

- **ffmpeg:** Ship a static build per OS inside the bundle (`vendor/ffmpeg/<os>/ffmpeg[.exe]`). Backend must resolve the ffmpeg path from config/bundle, **not** assume it's on `PATH`. Add `FFMPEG_PATH` (default: bundled binary in standalone, `ffmpeg` on PATH in server).
- **yt-dlp:** Already a Python dependency (in-process resolver). Because YouTube changes break yt-dlp frequently, standalone must **self-update yt-dlp** independently of app releases:
  - On startup (throttled to once/day), check for and pip-install/upgrade `yt-dlp` into the user-writable runtime, preferring the newer of bundled vs. downloaded.
  - Surface a non-blocking toast if playback fails in a way consistent with an outdated extractor: "Try Update Streaming Engine."
- Licensing: bundling ffmpeg (LGPL/GPL build) requires shipping its license text. Add `THIRD_PARTY_LICENSES.txt` to the installer.

### 3.4 Installers

- **Windows:** Inno Setup or MSIX → `MySpotify-Setup-x.y.z.exe`. Install per-user (no admin), Start-menu shortcut, optional run-at-login.
- **macOS:** `.dmg` with a `.app` bundle. Note code-signing/notarization is needed to avoid Gatekeeper warnings (document as a known first-run "right-click → Open" step if unsigned).
- **Linux:** **AppImage** (no install, portable) as primary; optionally a `.deb`.
- All artifacts produced by CI (see §9) and attached to GitHub Releases.

---

## 4. Auth in standalone mode

The biggest friction in the current model is Google OAuth, which **requires a public domain and registered redirect URIs** — impossible for a localhost app.

- **Local single-user account:** On first run, the backend auto-provisions one local user (e.g. `local`) with `role = 'admin'` and **no password**. The web UI auto-logs-in by minting a normal JWT for that user, so no login screen appears in standalone mode.
- **JWT still used internally:** Keep the existing JWT + signed-stream-URL machinery unchanged — it works fine over loopback and avoids a second code path. The only change is *how* the first token is obtained (local grant vs. OAuth).
- **OAuth becomes optional:** If the user later sets `GOOGLE_CLIENT_ID` and a domain, the login screen returns. Standalone simply skips the OAuth UI when no client ID is configured.
- **Security posture:** Binding to `127.0.0.1` only means no LAN exposure by default. The auto-login token must be scoped to loopback. If the user opts into "remote control from phone" (§6), require a real password/pairing PIN before binding to `0.0.0.0`.

**Backend changes:**
- New endpoint `POST /api/v1/auth/local` (enabled only when `APP_PROFILE=standalone`): returns access + refresh tokens for the local user; refuses to run on non-loopback requests.
- `GET /api/v1/config` reports `profile` and `auth_mode` (`local` | `oauth` | `password`) so the web UI knows whether to render the login modal.
- Web UI (`main.js`): when `auth_mode === 'local'`, skip the auth modal and call `/auth/local` on load.

---

## 5. Storage & paths

Replace hardcoded Docker `/app/...` paths with OS-appropriate, user-writable locations resolved at runtime (use the **`platformdirs`** package).

Base dir = `platformdirs.user_data_dir("MySpotify", "iwozere")`:

| Logical | Server default (today) | Standalone default |
| :------ | :--------------------- | :----------------- |
| Database | `/app/db/myspotify.db` | `<data>/db/myspotify.db` |
| Library  | `/app/library` | `<data>/library` (user can repoint to e.g. `~/Music`) |
| Cache    | `/app/cache` | `<cache>/cache` |
| Temp     | `/tmp/myspotify_cache` | `<cache>/temp` |
| Logs     | container stdout | `<data>/logs/` |

- All of `DATABASE_URL`, `MUSIC_PATH`, `CACHE_DIR`, `TEMP_DIR` already exist as config; standalone just computes different defaults. No business-logic changes — keep reading them from config.
- First run creates these dirs and seeds an empty DB via Alembic.
- A **Settings screen** (web UI) lets the user change the library location (e.g. point at their existing `~/Music`) and cache size limit, writing to a local `config.json` in the data dir.

---

## 6. Mobile path

A phone cannot realistically run yt-dlp + ffmpeg server-side, so true "self-contained on the phone" is a stretch goal. Two staged options:

### 6.1 Phase A — "Home Remote" (reuses existing Flutter app)
- The desktop standalone instance can optionally bind to `0.0.0.0:<port>` (guarded by a pairing PIN, §4) so the phone on the same Wi-Fi connects to `http://<pc-lan-ip>:<port>`.
- Add **mDNS/Bonjour advertisement** (`_myspotify._tcp`) from the desktop app and **discovery** in the Flutter settings screen, so the phone finds "MySpotify on Alex's-PC" without typing an IP.
- Everything else (the entire `/api/v1` surface) already works — the mobile app just needs a discovered base URL instead of a typed domain.

### 6.2 Phase B — On-device (later, separate CR)
- Replace the server resolver with an on-device YouTube resolver (`youtube_explode_dart`) feeding `just_audio` directly, plus on-device library. This removes the need for a PC entirely but is a large effort and extractor-fragility risk — explicitly out of scope here, flagged for a future `features-v8`.

---

## 7. UX for first run

- **Zero-config default:** Launch → window opens → search works immediately. No accounts, no keys.
- **Optional keys panel** in Settings: `GROQ_API_KEY` (AI Shuffle) and `GEMINI_API_KEY` (Hum-to-Search) are clearly marked optional; the related buttons stay hidden/disabled until set, exactly as the server already degrades when these are unset.
- **Disclaimer on first launch:** Show the existing disclaimer modal once on first run (persist "accepted" in local config) — reuses the `#disclaimer-modal` already in `index.html`.
- **Update channel:** A small "vX.Y.Z — up to date / update available" indicator in Settings (GitHub Releases check), separate from the yt-dlp engine update.

---

## 8. Configuration additions

Add to `backend/app/config.py`:

| Variable | Default (standalone) | Description |
| :------- | :------------------- | :---------- |
| `APP_PROFILE` | `server` | `server` or `standalone`; selects bind, auth, and path defaults. |
| `BIND_HOST` | `127.0.0.1` | Loopback by default in standalone; `0.0.0.0` only via explicit "Home Remote" opt-in. |
| `BIND_PORT` | `8000` (auto-fallback) | Preferred local port; falls back to ephemeral if taken. |
| `FFMPEG_PATH` | bundled binary | Absolute path to ffmpeg; standalone points at the vendored build. |
| `YTDLP_AUTO_UPDATE` | `True` | Daily self-update of yt-dlp in standalone. |
| `DATA_DIR` | `platformdirs` user-data dir | Root for DB, library, cache, logs (drives the §5 defaults). |
| `LOCAL_PAIRING_PIN` | — | Required before binding to `0.0.0.0` for phone access. |

`DOMAIN`, `GOOGLE_CLIENT_ID`, OAuth secrets become **optional** in standalone (no validation error when blank).

---

## 9. Build & release pipeline

- **GitHub Actions matrix** (`windows-latest`, `macos-latest`, `ubuntu-latest`):
  1. Set up Python, install backend deps.
  2. Download/cache the per-OS static ffmpeg into `vendor/`.
  3. PyInstaller one-folder build of `desktop.py`.
  4. Package: Inno Setup (Win), `create-dmg` (mac), `appimagetool` (Linux).
  5. Smoke test: launch headless, poll `/health`, run a search against a stub, assert 200.
  6. Upload artifacts to the GitHub Release on tag push.
- **Versioning:** Reuse the existing app version string (currently `v2.9.x`). Keep the web UI cache-buster rule from `AGENTS.md` §1.1 unchanged — bundled assets still ship inside the backend.

---

## 10. Risks & mitigations

| Risk | Mitigation |
| :--- | :--------- |
| **yt-dlp breaks when YouTube changes** (highest risk for non-technical users) | Daily self-update (§3.3) + visible "Update Streaming Engine" action + clear error toast. |
| ffmpeg bundling bloats the download (~30–80 MB) | One-folder build, per-OS static minimal build, document size. |
| macOS Gatekeeper / Windows SmartScreen warnings on unsigned binaries | Document "right-click → Open" first-run step; pursue signing/notarization before a wide release. |
| Port 8000 already in use | Ephemeral-port fallback; write actual port to runtime file the shell reads. |
| Antivirus false-positives on PyInstaller one-file | Use one-folder builds; submit to vendors if flagged. |
| Legal exposure | Reuse existing personal-use disclaimer (README + in-app modal); show it on first run. |

---

## 11. Implementation phases (suggested order)

1. **Profile plumbing:** add `APP_PROFILE`, `platformdirs` paths, `FFMPEG_PATH`; make `DOMAIN`/OAuth optional. *(Backend-only, no packaging — verifiable by running locally with `APP_PROFILE=standalone`.)*
2. **Local auth:** `POST /auth/local`, `auth_mode` in `/config`, web UI auto-login. *(Now it runs with zero config in a normal browser at `127.0.0.1:8000`.)*
3. **Launcher + browser-open** (`desktop.py`): bundle nothing yet, just start uvicorn and open the default browser. *(First "double-click runs it" milestone via a `.bat`/`.sh`.)*
4. **PyInstaller bundle + vendored ffmpeg + yt-dlp self-update.** *(First real distributable folder.)*
5. **Installers + CI release matrix** (§9).
6. **pywebview shell** for a real app window (replaces browser-open).
7. **Mobile "Home Remote"**: opt-in `0.0.0.0` bind + PIN + mDNS discovery in Flutter.

Phases 1–3 deliver a working, zero-config local app for technical users and de-risk everything before investing in packaging.

---

## 12. Related documents

- [system-specification.md](system-specification.md) — current server architecture and full API surface (the shared backend this CR repackages).
- [docker.md](docker.md) — the existing `server` profile deployment.
- [local-setup.md](local-setup.md) — local dev and OAuth setup (the friction this CR removes for end users).
- [features-v5.md](features-v5.md) — permanent library import (the "collect your own library over time" mechanism this edition leans on).
- README "Personal project" / "Disclaimer" notices — reused as the first-run disclaimer.
</content>
</invoke>
