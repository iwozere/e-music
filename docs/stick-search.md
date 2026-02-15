# UI/UX Improvement: Search Navigation & Header Pinning

## Requirements
1. **Sticky Search Header:** - Modify `style.css` to make `.search-container` use `position: sticky; top: 0;`.
   - Add a background color or glassmorphism effect (`backdrop-filter: blur(12px)`) to the sticky header so tracks don't overlap visually when scrolling behind it.
   - Increase the `z-index` of the search container to stay above the track cards.

2. **Unified Search Logic:**
   - When the **"Search" nav-item** is clicked:
     - Automatically scroll the `.main-content` to the top.
     - Set focus to the `#main-search` input field.
   - Remove any separate "search view" logic if it results in an empty screen.

3. **Scroll Fix:**
   - Ensure that pinning the search bar doesn't break the **Intersection Observer** (the sentinel should still trigger when the bottom of the list is reached).

4. **Cross-platform Readiness:**
   - Ensure the sticky header works correctly in the **Android WebView** and is ready for the future **iOS build**, specifically handling the top safe-area-inset.