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