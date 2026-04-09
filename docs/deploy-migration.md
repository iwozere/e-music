# Deploy migration guide (e-music)

This document summarizes **breaking and operational changes** when upgrading from older installs (pre P0–P2 hardening). Use it when deploying to a new host or upgrading an existing Docker/server deployment.

## 1. Environment variables (`.env`)

Add or update these keys (see root `.env.example`):

| Variable | Notes |
|----------|--------|
| `ADMIN_EMAILS` | Comma-separated emails that receive **admin** (required for `POST /api/v1/system/index` and `GET /api/v1/system/storage`). The old “first registered user is admin” behavior is removed. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Default **60** (was up to 30 days). Clients must use **refresh tokens**. |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Default **30**. |
| `STREAM_URL_TTL_SECONDS` | Lifetime of signed streaming URLs (default **600**). |
| `STREAM_URL_SIGNING_SECRET` | Optional; defaults to `JWT_SECRET` if unset. |
| `PUBLIC_API_BASE_URL` | **Recommended behind a reverse proxy.** Public origin of the API (no path), e.g. `https://api.e-music.win`. Used to build **signed stream URLs** and `api_base_url` in `GET /api/v1/config`. If unset, the app uses the request URL (may be wrong if the app only sees internal `http://backend:8000`). |

After changing `ADMIN_EMAILS`, **restart** the backend so `ensure_admin_roles()` can promote existing users.

## 2. API version prefix (**P2**)

All JSON API routes are under **`/api/v1`** (health check stays at **`/health`**).

- Auth: `/api/v1/auth/...`
- Tracks: `/api/v1/tracks/...`
- Playlists: `/api/v1/playlists/...`
- System (admin): `/api/v1/system/...`
- Public config: **`GET /api/v1/config`** (replaces `/auth/config` and `/system/config`).

Update:

- **Flutter / mobile:** `API_BASE_URL` must include the prefix, e.g. `https://api.example.com/api/v1`.
- **Web static UI:** `api.js` uses `origin + '/api/v1'` as the API root (same host as the UI).
- **Google Cloud Console**
  - **OAuth redirect URI:** e.g. `https://api.example.com/api/v1/auth/callback` (match `GOOGLE_REDIRECT_URI` in `.env`).
  - **GIS “Sign in with Google”** authorized origins / JS origins: unchanged (page origin).
  - **Authorized redirect URIs** for the GIS **server** / OAuth client: include every `…/api/v1/auth/google/login` you use per hostname, same rules as before (origin of the **page** that loads the button).

## 3. Client behavior changes (P0–P1 recap)

- **Registration:** `POST /api/v1/auth/register` with **JSON body** `{ "username", "email", "password" }` (not query parameters).
- **Tokens:** Login and Google flows return **`access_token`**, **`refresh_token`**, **`expires_in`**. Store both; call **`POST /api/v1/auth/refresh`** when the access token expires.
- **Playback:** Unauthenticated streaming is disabled. Obtain a URL via **`POST /api/v1/tracks/stream/grant`** (Bearer), then use the returned **`stream_url`** (HMAC-signed; no JWT in the query).

## 4. Database

On first start after upgrade, SQLModel creates the **`refreshtoken`** table. Existing SQLite files are compatible; no manual migration script is required for that table.

## 5. Error responses (**P2**)

JSON errors follow a common shape:

```json
{
  "code": "string",
  "message": "string",
  "detail": null
}
```

Do not rely on raw FastAPI `detail`-only payloads in new code. **Stack traces** are not returned to clients.

## 6. Smoke test after deploy

1. `GET https://<host>/health` → `200`.
2. `GET https://<host>/api/v1/config` → `google_client_id`, `api_base_url`.
3. Log in (password or Google); confirm **`/api/v1/auth/me`** with Bearer access token.
4. `POST /api/v1/tracks/stream/grant` with a real `track_id` → non-empty `stream_url`.
5. As an admin email, `GET /api/v1/system/storage` → `200`.

## 7. Rollback

If you must roll back, restore the previous image/commit and **previous `.env`**. Refresh-token rows may exist in SQLite; older code may ignore that table. Re-forward Google redirect URIs to the legacy paths if you revert the `/api/v1` prefix.

## 8. Reference

- Interactive OpenAPI: **`/docs`** (paths are shown with the `/api/v1` prefix).
- Standard error JSON: `code`, `message`, `detail` on failed requests; responses include **`X-Request-ID`** when the middleware runs.
