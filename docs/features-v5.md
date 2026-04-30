# Technical Specification: Permanent Library Import and Contextual AI Shuffle

## 1. Permanent Library Import (Collector Feature)

**Objective:** When a user saves a track to their library, it must be physically moved from the temporary cache to a structured permanent storage with embedded metadata.

### Backend Requirements (Python / yt-dlp / Mutagen):

- **Download & Processing:**
  - Use `yt-dlp` with the following flags: `--format bestaudio`, `--extract-audio`, `--audio-format mp3`, `--audio-quality 0`.
  - Mandatory embedding: `--embed-thumbnail --add-metadata`.
  - Use the `mutagen` library to finalize and verify ID3 tags (Title, Artist, Album, cover art via APIC).
  - Only MP3 files are imported into the library; `.webm`/`.aac` passthrough artifacts remain in cache only.

- **Storage Structure:**
  - Implement file movement logic using the following path template (matching the existing `library_import.py` logic):
    `{MUSIC_PATH}/{Artist}/{Album}/{Track_Title}.mp3`
  - `MUSIC_PATH` is `/app/library` inside the container (mapped from host via docker-compose).
  - Artist and Album directories are resolved **case-insensitively** to avoid duplicate folders on Linux hosts (e.g., `Smokie` and `SMOKIE` map to the same folder).
  - Album art is saved as `{MUSIC_PATH}/{Artist}/{Album}/album.png`.
  - A `{MUSIC_PATH}/{Artist}/{Album}/album_meta.json` sidecar tracks which user saved which track.
  - If Artist or Album is unknown, use `"Unknown Artist"` / `"Unknown Album"` as defaults.

- **Database Synchronization:**
  - After moving the file, update the database record: set `is_cached = True` and update the `local_path`.
  - The Library Watcher (`watcher.py`) auto-indexes the new file so it appears immediately in the "Local Files" section — no manual trigger needed.

## 2. Contextual AI Shuffle Algorithm

**Objective:** Provide intelligent queue continuation ("Radio Mode") based on the current playback context.

### Recommended LLM: Groq API (`llama-3.1-8b-instant` or `llama-3.3-70b-versatile`)

**Why Groq:**
- Generous free tier: ~14,400 requests/day at no cost (no credit card required for basic use).
- OpenAI-compatible API — simple to integrate, minimal code changes if switching models later.
- Very fast inference (sub-second), which matters for queue continuation UX.
- `llama-3.1-8b-instant` is sufficient for structured JSON music recommendations; use `llama-3.3-70b-versatile` if output quality needs improving.
- API key via `GROQ_API_KEY` environment variable.

**Fallback option:** Gemini 2.0 Flash (`gemini-2.0-flash`) via Google AI Studio — also free (15 RPM, 1M tokens/day), but requires a Google account and has stricter rate limits.

### Data Collection Scenarios (Prompt Context):

1. **Playlist or "Liked Songs":**
   - **Trigger:** The last track in the current playlist/liked list finishes.
   - **Data:** All tracks from the current session in the exact order they were played (respecting the shuffled order if Shuffle was active).

2. **Search / Single Track (Authenticated User):**
   - **Trigger:** A single track ends with an empty queue.
   - **Data:** The last **N=10** entries from the `play_history` table for the specific `user_id`.

3. **Search / Single Track (Anonymous User):**
   - **Trigger:** A single track ends with an empty queue.
   - **Data:** Only the **1** last played track.

### System Prompt:

```text
You are a professional music curator. The user has just finished listening to this sequence: [LIST_OF_TRACKS].
Based on the genre, tempo, and mood of this specific sequence, suggest 10 new similar tracks to continue the session.
Return ONLY a JSON array of objects: [{"artist": "...", "title": "..."}].
Do not suggest tracks that are already in the provided list.
```

### Response Processing Logic:

1. Parse the JSON response.
2. For each `"Artist - Title"` pair, perform an automated internal search via the existing `ytmusic.py` service.
3. Select the best match `remote_id` and append it to the playback queue.

## 3. UI and Mobile Integration

### Web/Desktop UI:

- Add an "AI Shuffle" button (icon: `lucide-sparkles`).
- Display a Toast notification when activated: `"AI is curating your next tracks..."`.

### Mobile App (Flutter):

**Context:** The app already has `path_provider` and `http` packages in `pubspec.yaml` — no new dependencies needed.

**When a track is saved to the server library:**
1. Call `POST /api/v1/tracks/{id}/save-to-library` (new endpoint, requires auth).
2. On success, download the MP3 to device internal storage:
   - Use `getApplicationDocumentsDirectory()` from `path_provider` for the destination — no special Android permissions required (internal app storage).
   - Store at `{appDocumentsDir}/tracks/{track_id}.mp3`.
   - Stream download using the existing `http` package.
3. Persist the local path in the Track object's existing `localPath` field.

**Playback priority** (in `AudioPlayerBloc`):
- If `track.localPath` is set and the local file exists → play from local path using `just_audio` `AudioSource.file()`.
- Otherwise → call `getStreamUrl(trackId)` and stream from server as today.

## 4. Technical Requirements

- **Docker:** Existing volume mapping is correct — `${MUSIC_HOST_ROOT:-${MUSIC_PATH}}/library:/app/library`. No changes needed.
- **FFmpeg:** Use latest available version for high-quality re-encoding and thumbnail embedding.
- **Environment:** Load API key from `.env` file — add `GROQ_API_KEY` (and optionally `GEMINI_API_KEY` as fallback).
- **Database:** Add a `play_history` table with `user_id` (nullable FK), `track_id` (FK), and `played_at` (datetime, indexed) fields. This is separate from the existing `UserActivity` aggregate table.
