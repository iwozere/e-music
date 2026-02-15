# Stability & Architecture Refactoring

## 1. Modularize JavaScript (No Build Tools)
- **Requirement:** Split `main.js` into `api.js` (network calls), `player.js` (audio logic), and `ui.js` (DOM manipulation).
- **Goal:** Reduce bug regressions by isolating the player logic from the search/scroll logic.

## 2. Robust Pagination (Intersection Observer)
- **Requirement:** Refactor infinite scrolling to use the **Intersection Observer API**.
- **Details:** - Insert a `div id="load-more-trigger"` at the end of the track list.
    - Fetch new results only when this trigger enters the viewport.
    - Implement a "Loading" state to prevent duplicate concurrent API calls.

## 3. State Consistency
- **Requirement:** Ensure all UI updates (likes, play status) are driven by a single `state` object. 
- **iOS/Cross-platform Note:** Keeping the state predictable is key for ensuring the Android WebView doesn't desync metadata from the UI.

## 4. Cleanup
- **Requirement:** Implement a "Debounce" function for the search input to prevent firing 10 API calls while typing.