# Stability Fixes & New Features: Playback and Playlist Management

## 1. Bugfix: "Play All" for Non-Cached Tracks
**Problem:** The "Play All" function currently fails or skips tracks that were added from Search but haven't been played/cached yet.
**Requirement:** - Refactor the `playAll()` function (and any logic inside `ui.js`) to support hybrid track sources.
- Ensure the player checks if a track has a local `id` or only a `remote_id`.
- If `is_cached` is false, fallback to the `/stream/{track_id}` endpoint using the remote identifier.

## 2. Feature: Playback Randomization (Shuffle)
**Objective:** Give users more variety when listening to their library or liked songs.
**Requirement:**
- **UI:** Add a "Play All Random" button in the headers of "Your Library" and "Liked Songs".
- **Logic:** Implement a `playRandom()` function in `player.js` or `ui.js`.
- **Implementation:** Use a Fisher-Yates shuffle algorithm to randomize the `state.currentTracksContext` before starting playback of the first track in the new shuffled list.

## 3. Feature: Delete Playlist
**Objective:** Allow users to manage and remove unwanted playlists.
**Requirement:**
- **Backend (main.py):** Add a `DELETE /playlists/{playlist_id}` endpoint. Ensure it only deletes the playlist record and its associations, NOT the actual tracks from the database.
- **Frontend API (api.js):** Add `API.deletePlaylist(playlistId)` function.
- **UI (ui.js):** - Add a "Delete" icon/button (using `lucide-trash-2`) to the playlist view or card.
    - Implement a confirmation dialog (`window.confirm`) before executing the deletion to prevent accidental loss.
    - After deletion, automatically redirect the user to the "Library" view and refresh the list.

## 4. Technical Guardrails & iOS Readiness
- **Icons:** Always call `UI.initIcons()` after rendering new elements to ensure Lucide icons appear.
- **State Integrity:** When deleting a playlist, ensure `state.currentView` is updated so the app doesn't try to render a non-existent playlist.
- **Mobile Prep:** Ensure the delete button has a sufficient touch target size (minimum 44x44px) for the Android WebView and future iOS port.