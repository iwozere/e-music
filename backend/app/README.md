# MySpotify Backend

## Overview
The MySpotify Backend is a FastAPI-based application that serves as the core of the MySpotify music ecosystem. It provides endpoints for user authentication, unified music search (local library + YouTube Music), and high-performance audio streaming with local caching.

## Features
- **Unified Search**: Seamlessly search both your local collection and YouTube Music.
- **Background Indexing**: Automatically monitors your library folder for new MP3 files.
- **Streaming Proxy**: Streams YouTube audio with on-the-fly local caching to save bandwidth.
- **Multi-user Support**: Secure authentication with Google OAuth2 or traditional Username/Password registration.
- **AI Shuffle (Radio Mode)**: `POST /api/v1/tracks/ai-shuffle` — sends listening context to Groq LLM, returns 10 curated track suggestions resolved via YouTube Music. Requires `GROQ_API_KEY`.
- **Hum-to-Search**: `POST /api/v1/ai/identify` — accepts a multipart audio upload, sends it inline to Google Gemini, and returns artist/title/confidence. Requires `GEMINI_API_KEY`. Rate-limited to 3 requests/minute per user.

## Quick Start
Example code showing how to use the search functionality:

```python
import httpx

async def search_tracks(query: str):
    async with httpx.AsyncClient() as client:
        response = await client.get(f"https://e-music.win/search?q={query}")
        return response.json()
```

## Integration
This module integrates with:
- **YouTube Music API**: For external track discoveries.
- **SQLModel/SQLite**: For persistent metadata storage and user activity.
- **Watchdog**: For real-time filesystem monitoring of the music library.

## Configuration
The backend is configured via a `.env` file containing:
- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`: For OAuth2.
- `JWT_SECRET`: For secure token signing.
- `DATABASE_URL`: Path to the SQLite database.
- `PUBLIC_API_BASE_URL` (optional): Public API origin when behind a reverse proxy.
- `YTDLP_COOKIES_FILE`, `YTDLP_YOUTUBE_PLAYER_CLIENT`, `YTDLP_EXTRA_ARGS` (optional): YouTube / `yt-dlp` behavior on the server.
- `GROQ_API_KEY` (optional): Enables AI shuffle. Get a free key at console.groq.com.
- `GEMINI_API_KEY` (optional): Enables hum-to-search. Get a free key at aistudio.google.com.
- `GEMINI_MODEL` (default `gemini-2.5-flash`): Gemini model used for melody identification.
- `IDENTIFY_MIN_CONFIDENCE` (default `75`): Minimum confidence threshold (0–100); results below this return a not-found error.

## Related Documentation
- [Requirements](docs/Requirements.md) - Technical requirements
- [Design](docs/Design.md) - Architecture and design
- [Tasks](docs/Tasks.md) - Implementation roadmap
