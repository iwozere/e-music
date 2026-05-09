# Local Backend Setup Guide

Follow these steps to run the MySpotify backend on your local Windows machine.

## 1. Environment Preparation

Ensure you have Python 3.10+ installed.

```powershell
# Navigate to the project root
cd c:\dev\cursor\e-music

# Create a virtual environment
python -m venv .venv

# Activate the virtual environment
.venv\Scripts\Activate.ps1
```

## 2. Install Dependencies

```powershell
pip install -r backend/requirements.txt
```

## 3. Configuration (.env)

The backend looks for a `.env` file in the current directory or the project root.

> [!NOTE]
> I've updated the backend to automatically pick up the `.env` from the project root even when running from the `backend/` folder.

- `DATABASE_URL`: Set this to the project's standard database folder.
  - **Recommended**: `DATABASE_URL=sqlite:///./backend/app/db/myspotify.db`
  - *Note: The folder `backend/app/db/` is already ignored by git.*
- `MUSIC_PATH`: Ensure this points to your local music directory.
  - **Example**: `MUSIC_PATH=R:\e-music`
- `CACHE_DIR`: Where to store persistent YouTube cache.
  - **Example**: `CACHE_DIR=R:\e-music\cache`
- `TEMP_DIR`: Where to store temporary stream chunks.
  - **Example**: `TEMP_DIR=R:\e-music\temp_cache`
- `GROQ_API_KEY` (optional): Enables AI shuffle / radio mode. Get a free key at [console.groq.com](https://console.groq.com).
- `GEMINI_API_KEY` (optional): Enables hum-to-search melody identification. Get a free key at [aistudio.google.com](https://aistudio.google.com).
  - Default model: `gemini-2.5-flash` (free tier). Override with `GEMINI_MODEL=<model-id>`.

## 4. Running the Backend

Run the server from the `backend` directory to ensure module imports resolve correctly.

```powershell
cd backend
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## 5. Verifying the Setup

Open your browser and navigate to:
- **API Health**: [http://localhost:8000/health](http://localhost:8000/health)
- **API Docs**: [http://localhost:8000/docs](http://localhost:8000/docs) (Swagger UI)

## 6. Google Cloud Console — OAuth configuration

Use this checklist whenever you see **`redirect_uri_mismatch`**, **`Access blocked`**, or sign-in works on one device/URL but not another.

### Where to go in Google Cloud

1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Select the **project** that owns your OAuth clients.
3. Menu: **APIs & Services** → **Credentials**.
4. Under **OAuth 2.0 Client IDs**, open the **Web application** client whose **Client ID** matches `GOOGLE_CLIENT_ID` in your `.env` (not the Android client).

If you have no Web client yet: **Create credentials** → **OAuth client ID** → Application type **Web application**.

**Also ensure** **OAuth consent screen** is configured (Testing / Production and test users if needed).

### How this app uses Google (two ideas to keep separate)

| Mechanism | Where it’s used | Redirect / callback URL |
|-----------|------------------|-------------------------|
| **Google Identity Services (GIS)** — “Sign in with Google” button, `ux_mode: redirect` | Browser loads `login_uri` from the **same origin as the page** | **`{origin}/auth/google/login`** e.g. `https://e-music.win/auth/google/login` |
| **Authorization code flow** (optional; `/auth/login` URL builder) | Server uses `GOOGLE_REDIRECT_URI` from `.env` | Whatever you set in `.env`, often **`https://api…/auth/callback`** |

The **GIS** button always sends users back to **`window.location.origin` + `/auth/google/login`**. So **every hostname you use to open the UI** needs matching Console entries (see below).

### Authorized JavaScript origins

**Path:** same Credentials screen → **Authorised JavaScript origins** → **Add URI**.

Add **one entry per origin** (scheme + host + port only — **no** path, **no** trailing slash):

Examples you may need:

- Local dev (FastAPI serves the UI): `http://localhost:8000`
- Phone / another PC on LAN: `http://192.168.x.x:8000` (use your real IP and port)
- Public site (UI): `https://e-music.win`
- If you sometimes open the UI on the API host: `https://api.e-music.win`

### Authorized redirect URIs

**Path:** **Authorised redirect URIs** → **Add URI**.

Add **full URLs including path**. For GIS sign-in you **must** include, for **each** JavaScript origin you use:

- `{that_origin}/auth/google/login`

Examples:

- `http://localhost:8000/auth/google/login`
- `http://192.168.x.x:8000/auth/google/login`
- `https://e-music.win/auth/google/login`
- `https://api.e-music.win/auth/google/login` *(only if users actually load the app from `api.…`)*

For the **code flow** (if you use `/auth/callback` and `GOOGLE_REDIRECT_URI` in `.env`), also add the exact URIs you configure there, e.g.:

- `http://localhost:8000/auth/callback`
- `https://api.e-music.win/auth/callback`

### Common mistake: `e-music.win` vs `api.e-music.win`

If the browser address bar is **`https://e-music.win`**, GIS uses **`https://e-music.win/auth/google/login`**.  
Listing only **`https://api.e-music.win/auth/google/login`** is **not** enough — Google will return **`redirect_uri_mismatch`**.

### After saving

Click **Save**. Changes can take a few minutes to apply.

### Android app

The **Android** OAuth client (`GOOGLE_CLIENT_ID_ANDROID`, etc.) is configured separately (package name + SHA-1). Do **not** put LAN URLs there; use the **Web** client for the browser-based sign-in described above.
