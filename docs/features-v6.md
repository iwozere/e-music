# Specification: "Hum-to-Search" (Audio Identification) Feature

## 1. Objective
Implement a feature that allows users to record a 5-10 second audio clip of themselves humming or singing a melody, identify the track/artist using Gemini AI, and automatically find the matching song on YouTube.

## 2. Backend Implementation (ai_service.py / main.py)
**Goal:** Create a processing pipeline for audio identification.

- **Endpoint:** `POST /ai/identify`
- **Payload:** Multipart/form-data containing an audio file (e.g., `.wav`, `.m4a`, or `.opus`).
- **Processing Logic:**
    1. **Receive Audio:** Save the incoming stream to a temporary buffer.
    2. **Gemini Integration:** Use the `google-generativeai` SDK with the existing `GEMINI_API_KEY`.
    3. **Multimodal Prompt:**
       ```text
       "System Prompt: You are a music identification expert. 
       Task: Listen to the attached audio clip of a user humming/singing. 
       Identify the song title and artist.
       Output Format: Return ONLY a JSON object: {'artist': 'string', 'title': 'string', 'confidence': 0-100}. 
       If you cannot identify the song, return {'error': 'not_found'}."
       ```
    4. **Search Integration:** Upon successful identification, automatically trigger the existing `Youtube` function to retrieve the `remote_id` for the track.
    5. **Response:** Return the song metadata and the YouTube search result to the client.

## 3. Frontend Implementation (Mobile & Web)
**Goal:** Provide a simple UI for audio capture.

- **UI Elements:**
    - A "Microphone" button (icon: `lucide-mic`) in the Search bar.
    - A recording overlay/modal showing a 10-second countdown and a simple wave visualizer.
- **Client Logic:**
    - **Permissions:** Request microphone access on first use.
    - **Capture:** Record for exactly 7-10 seconds to ensure enough data for Gemini without excessive latency.
    - **Upload:** Send the compressed audio to the `/ai/identify` endpoint.
    - **Loading State:** Show a "Magic is happening... identifying melody" animation.

## 4. Technical Constraints & Performance
- **Audio Quality:** Use 16kHz or 44.1kHz mono to reduce file size.
- **Latency:** Ensure the backend cleans up temporary audio files immediately after the Gemini API call to save space on Raspberry Pi.
- **Error Handling:** - If Gemini returns a low confidence score, ask the user to "Try humming a bit louder or longer."
    - Handle `SocketTimeout` if the upload takes too long on mobile data.

## 5. Security
- Only authenticated users (if applicable) should use this endpoint to prevent Gemini API quota exhaustion by anonymous bots.
- Limit requests to 3 per minute per user.