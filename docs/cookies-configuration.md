# YouTube cookies configuration (`YTDLP_COOKIES_FILE`)

## Why

The backend uses `yt-dlp` to resolve YouTube audio URLs. Without authentication,
YouTube increasingly serves unauthenticated requests through **BotGuard / PO
token** challenges — yt-dlp ends up running a JavaScript runtime (Deno) to
mint a PO token on every cold resolve, which adds **~8 seconds** of latency
per track.

Supplying a logged-in `cookies.txt` sidesteps the PO token dance almost
entirely: resolves drop from ~10–12 s to **~1–3 s**, `clients=` collapses to a
single client (`tv` or `web`), and the chosen format becomes a proper
audio-only `m4a` instead of a muxed `mp4`.

You can verify the current behavior before and after the change by watching
the resolver's structured log line:

```bash
docker compose logs -f -t backend | grep --line-buffered "yt_resolver: resolved"
```

See [docker.md](docker.md) for the full log-reading recipes.

---

## Step 1 — Export `cookies.txt` from a logged-in browser

### Use a throwaway Google account

Cookies give anyone who holds the file full access to that YouTube account.

> **Do not use your primary Google account.**

Create a separate Google account just for this server (e.g. a "family music
server" account), then use it in a dedicated browser profile so its session
does not collide with your personal one.

### Install an open-source exporter extension

Use the audited, client-side-only **"Get cookies.txt LOCALLY"** extension —
everything happens locally, nothing is uploaded:

- **Chrome / Edge / Brave / Vivaldi**:
  [Chrome Web Store — Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)
- **Firefox**:
  [addons.mozilla.org — cookies.txt](https://addons.mozilla.org/en-US/firefox/addon/cookies-txt/)
  (or the "cookies.txt ONE click" fork)

Avoid unknown "cookie exporter" extensions — several popular ones have been
flagged as malware.

### Export the YouTube cookies

1. In the dedicated browser profile, open **https://www.youtube.com** and sign
   in with the throwaway account.
2. Play any video for ~10 seconds so YouTube issues the session cookies
   yt-dlp relies on (`LOGIN_INFO`, `VISITOR_INFO1_LIVE`, `__Secure-3PSID`, …).
3. While still on `youtube.com`, click the extension icon.
4. Choose **"Current Site"** (not "All sites") and export as **`cookies.txt`**
   (Netscape format — **not** JSON).
5. Save the file locally as `cookies.txt`.

Sanity check: the first line of the file must be:

```
# Netscape HTTP Cookie File
```

and you should see rows for `.youtube.com`. If the file starts with `{`, you
exported JSON by mistake — try again.

---

## Step 2 — Copy the file to the Pi

From your workstation (adjust source path / user / host):

```powershell
# Windows (PowerShell)
scp cookies.txt alkotrader@raspberrypi:/opt/apps/e-music/cookies.txt
```

```bash
# macOS / Linux
scp cookies.txt alkotrader@raspberrypi:/opt/apps/e-music/cookies.txt
```

On the Pi, lock the file down to your user only:

```bash
cd /opt/apps/e-music
chmod 600 cookies.txt
ls -l cookies.txt
```

`600` (owner read/write only) keeps the session cookies out of reach of other
local users. The container can still read it because it mounts the host file
directly (see Step 3).

---

## Step 3 — Mount the file into the backend container

Edit `docker-compose.yml` and add **one line** under `backend.volumes:`:

```yaml
services:
  backend:
    volumes:
      - ${MUSIC_HOST_ROOT:-${MUSIC_PATH}}/library:/app/library
      - ${MUSIC_HOST_ROOT:-${MUSIC_PATH}}/cache:/app/cache
      - ${MUSIC_HOST_ROOT:-${MUSIC_PATH}}/db:/app/db
      - ./backend/app:/app/app
      - ./cookies.txt:/app/cookies.txt:ro   # <-- add this
```

The `:ro` suffix mounts the file read-only so the container cannot rewrite it.

---

## Step 4 — Point the backend at the file via `.env`

Edit `/opt/apps/e-music/.env` and add (or uncomment):

```env
YTDLP_COOKIES_FILE=/app/cookies.txt
```

> **Important**: this is the path **inside the container**, not on the host —
> the compose volume mount maps the two.

### Optional: drop the serial client fallback

Once cookies are working, `tv` (or `web`) will return usable audio-only
formats directly. Skip the `mweb` fallback to avoid the initial serial client
retry:

```env
YTDLP_YOUTUBE_PLAYER_CLIENT=tv,web
```

You can drop `web` too (leaving just `tv`) once you confirm `tv` works
reliably for your content.

---

## Step 5 — Recreate the backend

Only compose config + env changed, so no rebuild is needed:

```bash
cd /opt/apps/e-music
docker compose up -d --force-recreate backend
```

### Sanity checks

**1. The file is visible inside the container:**

```bash
docker compose exec backend ls -l /app/cookies.txt
docker compose exec backend head -1 /app/cookies.txt
```

Expected from the second command:

```
# Netscape HTTP Cookie File
```

**2. The backend picked up the env var:**

```bash
docker compose exec backend printenv YTDLP_COOKIES_FILE
```

Expected:

```
/app/cookies.txt
```

**3. Trigger a resolve and read the timing.**

Play a track in the app, then:

```bash
docker compose logs -f -t backend | grep --line-buffered "yt_resolver: resolved"
```

What to expect on a successful cookie setup:

| Field            | Before cookies           | After cookies                 |
|------------------|--------------------------|-------------------------------|
| `elapsed_ms`     | ~10 000–12 000           | **~1 000–3 000**              |
| `clients=`       | `tv,web,mweb`            | `tv` (or `web`)               |
| `ext` / `acodec` | `mp4` / `mp4a.40.2`      | **`m4a`** / `mp4a.40.2`       |
| `timing=` has …  | `ejs@…`, **`po_token@~8000`** | no `po_token` entry      |

The `po_token@…` entry disappearing is the definitive sign the cookies are
working. If `ejs@…` still shows up but `po_token` is gone, that is just Deno
warming up once per resolve and is fine.

---

## Maintenance

### Cookies expire

- Short-lived cookies last hours; long-lived ones (`__Secure-3PSID`) usually
  survive weeks to months.
- Google can revoke the session at any time if it detects unusual activity.
- **Symptom of expired cookies**: `po_token@…` reappears in the `timing=`
  string and `elapsed_ms` shoots back up to ~10 s. When that happens:

  ```bash
  # Re-export cookies.txt in the browser, then:
  scp cookies.txt alkotrader@raspberrypi:/opt/apps/e-music/cookies.txt
  ssh alkotrader@raspberrypi
  cd /opt/apps/e-music
  chmod 600 cookies.txt
  docker compose restart backend
  ```

  No compose / env edits needed — the container re-reads the file at resolve
  time.

### Do not commit `cookies.txt`

The file contains a long-lived Google session. Add it to `.gitignore`
(project root):

```gitignore
# Session cookies for yt-dlp (never commit)
cookies.txt
```

### Rotating the throwaway account

If you ever suspect the cookies leaked:

1. Go to https://myaccount.google.com → **Security** → **Your devices** and
   sign the server session out.
2. Change the password on the throwaway account.
3. Re-export `cookies.txt` and re-upload (Step 2).

---

## Troubleshooting

**`docker compose exec backend ls /app/cookies.txt` says "No such file":**
the mount line is missing or `./cookies.txt` does not exist on the host.
Re-check Step 3 and confirm the file is next to `docker-compose.yml`.

**`printenv YTDLP_COOKIES_FILE` prints nothing:** the env var is not in
`.env` or the container was not recreated after the edit.
`docker compose up -d --force-recreate backend` to apply.

**Log still shows `po_token@…` after the change:**
1. Confirm Step 5 sanity checks 1 + 2 all pass.
2. Inspect a few lines of the cookies file:
   `docker compose exec backend tail -5 /app/cookies.txt`.
   You should see lines with `.youtube.com` and a `__Secure-3PSID` entry. If
   those are missing, re-export — the account was probably signed out while
   you exported.
3. If cookies are definitely valid but `po_token` keeps showing up, YouTube
   may be requiring a pre-minted PO token for your IP range (common on
   datacenter IPs). Follow the
   [yt-dlp PO Token Guide](https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide)
   and inject the token via `YTDLP_EXTRA_ARGS` in `.env`.

**`yt_resolver: extract_info failed`** with `Sign in to confirm you're not a
bot`: cookies are missing, stale, or the file is JSON instead of Netscape.
Re-export (Step 1) and re-upload (Step 2).

---

## Related documentation

- [docker.md](docker.md) — container lifecycle, logs, health checks
- [local-setup.md](local-setup.md) — end-to-end local bring-up
- [yt-dlp EJS wiki](https://github.com/yt-dlp/yt-dlp/wiki/EJS)
- [yt-dlp PO Token Guide](https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide)
