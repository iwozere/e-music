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

## 6. Google Auth Troubleshooting

If you see "Zugriff blockiert" (Access Blocked) or "Invalid Request" when logging in locally, you must whitelist your local environment in the [Google Cloud Console](https://console.cloud.google.com/apis/credentials):

1.  **Authorized JavaScript origins**:
    - `http://localhost:8000`
    - `http://localhost:3000` (if using a separate frontend)
2.  **Authorized redirect URIs**:
    - `http://localhost:8000/auth/google/login`

> [!IMPORTANT]
> Google can take up to 5 minutes to propagate these changes. If it doesn't work immediately after saving, wait a few minutes and try again.
