# Product Requirements: Music Player Enhancement (Quick Wins)

## Overview
Following the successful deployment of the core streaming infrastructure, we are moving into the "UX Polish" phase. The goal is to implement high-value features with minimal architectural changes, maintaining strict cross-platform readiness for future iOS integration.

## 1. System Integration: Media Session API
**Objective:** Allow the OS to control and display music metadata outside the browser.
- **Requirement:** Implement `navigator.mediaSession` in `main.js`.
- **Details:** - Update metadata (Title, Artist, Album, Artwork) whenever a track starts.
    - Set up action handlers for `play`, `pause`, `previoustrack`, and `nexttrack`.
- **iOS/Cross-platform Note:** This is natively supported by iOS Safari and is critical for lock-screen controls when wrapped in a WebView.

## 2. Playback: Queue Management ("Up Next")
**Objective:** Enable users to build a temporary sequence of tracks.
- **Requirement:** - Create a global `state.queue` array.
    - Add "Play Next" and "Add to Queue" options to each track card.
    - Implement an `onEnded` listener on the audio element to automatically trigger the next track in the queue.
- **Logic:** If the queue is empty, stop playback or trigger "Radiomode" (suggested related tracks).

## 3. UX: Keyboard Controls (Hotkeys)
**Objective:** Improve desktop accessibility and power-user experience.
- **Requirement:** Global event listener for keyboard shortcuts.
- **Shortcuts:**
    - `Space`: Toggle Play/Pause (prevent default page scroll).
    - `ArrowRight` / `ArrowLeft`: Seek forward/backward by 10 seconds.
    - `m`: Toggle Mute.
- **Implementation:** Ensure listeners are disabled when the user is typing in the search bar.

## 4. Performance: Smart LRU Backend Caching
**Objective:** Reduce bandwidth and improve latency for frequently played tracks.
- **Requirement:** - Implement a simple Least Recently Used (LRU) cache on the backend.
    - If a YouTube track is played more than X times or completed, save the stream to the `/app/cache` directory.
    - Update `streamer.get_stream` to prioritize local cache files before hitting the YouTube API.

## 5. Mobile Readiness (iOS WebView Preparation)
**Objective:** Ensure all new features work in a constrained mobile environment.
- **Requirement:** - Use `ux_mode: 'redirect'` for all auth-related actions.
    - Avoid `window.open` or complex popups; use internal state transitions for UI.
    - Ensure all layouts are responsive and use touch-friendly targets (min 44x44px for buttons).

## 6. Refined Logic & UI Specifications

### Queue Management: "Hybrid" Visibility
- **Requirement:** Implement a toggleable "Up Next" sidebar.
- **Details:** - Users must see the upcoming list of tracks.
    - **Quick Win:** For now, focus on "Visibility" and "Removal" from the queue. Drag-and-drop reordering can be a secondary phase, but the UI should be prepared for it.
- **iOS Note:** A clear sidebar helps mobile users manage long listening sessions without navigating away from the player.

### Radio Mode: YouTube "Related" Integration
- **Requirement:** Use YouTube Music's "Related" API for the end-of-queue transition.
- **Logic:** - When the `state.queue` is empty, the backend should fetch a list of related tracks based on the *last* played song's `remote_id`.
    - This provides a much better "Spotify-like" discovery experience than a simple same-artist shuffle.

### Caching Strategy: The "Popularity" Rule
- **Requirement:** Set the Caching Threshold (X) to **3 full plays**.
- **Storage Management:** - Tracks played 3+ times move to `/app/cache`.
    - Implement a simple cleanup (automatic deletion of the oldest cached files) if the `/app/cache` directory exceeds a configurable size (e.g., 5GB).

### Media Session: Full System Control
- **Requirement:** Enable "Seeking/Scrubbing" via the OS Media Session.
- **Details:**
    - Implement `seekto` and `seekbackward/seekforward` action handlers.
    - Synchronize the `playbackState` (playing/paused) and `positionState` (current time/duration) accurately.
- **iOS Note:** Scrubbing from the lock screen is a "must-have" for a premium mobile feel.

---

## Implementation status (vs. this document)

Tracked against the current web dashboard (`backend/app/static/`) and backend. Use this to prioritize remaining “quick wins.”

| Area | Status | Notes |
| :--- | :----- | :---- |
| **Sec. 1 — Media Session metadata** | **Partial** | `player.js` sets `MediaMetadata` (title, artist, artwork) when playback starts. |
| **Sec. 1 / 6.4 — Media Session actions & position** | **Not done** | No `setActionHandler` for play/pause/previous/next; no `seekto` / seek ±; no `playbackState` or `positionState` updates (lock screen / OS controls limited). |
| **Sec. 2 — Queue core** | **Done** | `state.queue`, Play Next / Add to Queue on cards, `ended` → `playNext`, queue sidebar. |
| **Sec. 2 — End-of-queue “radio”** | **Not done (web)** | When queue and context wrap, player just continues in list; no call to `GET /api/v1/tracks/{id}/related`. |
| **Sec. 3 — Keyboard shortcuts** | **Not done** | No global hotkeys (Space / arrows / mute); search `keydown` only handles Enter. |
| **Sec. 4 / 6.3 — Caching** | **Mostly done** | Third play promotes YouTube tracks to persistent cache (`tracks.py` + `cache_manager`); `enforce_cache_limit()` drops oldest by **atime** when cache &gt; **5 GB** (hardcoded `MAX_CACHE_SIZE_GB`). Stream path prefers local file when cached. **Gap:** limit not env-configurable; eviction does not consult DB play counts (may delete “popular” files on disk while row still says cached). |
| **Sec. 5 — Mobile readiness** | **Partial** | Google `ux_mode: 'redirect'` is used in `main.js`; full responsive / 44px audit not documented here. |
| **Sec. 6.1 — Queue UI** | **Done (MVP)** | Toggle sidebar, list, remove item; **no** drag-and-drop reorder yet. |
| **Sec. 6.2 — Radio (related API)** | **Backend ready** | Endpoint exists; **web client** does not wire autoplay from related tracks. |

---

## Suggested roadmap (next improvements)

**From this document (finish the spec)**  
1. **Media Session (high impact, small scope):** `setActionHandler` for play, pause, previoustrack, nexttrack wired to existing controls; update `playbackState` on play/pause/ended.  
2. **Media Session position:** `timeupdate` (throttled) → `setPositionState` + `seekto` / `seekbackward` / `seekforward` handlers driving `audio.currentTime`.  
3. **Keyboard shortcuts** in `main.js` or `player.js`: guard when focus is in `input` / `textarea` / contenteditable.  
4. **Radio mode (web):** On `ended`, if queue empty and last track has `remote_id`, fetch related, append to `state.queue` or replace context (with user toggle “Autoplay similar”).  
5. **Cache policy hardening:** Make max cache GB configurable; on eviction, update or invalidate `Track` rows whose `local_path` was removed; optional “protect tracks with play_count ≥ N.”

**Additional ideas (not in the original list)**  
- **PWA:** `manifest.json`, icons, optional service worker for shell cache (offline branding only; streaming still online).  
- **A11y:** Visible focus styles, `aria-*` on player and queue, skip link to main content.  
- **Flutter parity:** Same keyboard + media session behavior on Android; reuse `/tracks/stream/grant` flow for native player.  
- **Observability:** Client-side breadcrumb or correlation id with `X-Request-ID` for support (“this play failed”).  
- **Quality-of-life web:** Persist queue in `sessionStorage`, optional “clear queue on navigate,” mini-player on small viewports.  
- **Testing:** Smoke tests for auth, stream grant, and liked/playlist navigation (Playwright or similar).

For API and deployment truth, prefer [system_specification.md](system_specification.md) and [docker.md](docker.md); this file remains the **product** wish list for player UX.