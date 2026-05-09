# Design

## Purpose
The backend serves as the bridge between various music sources and the MySpotify mobile/web clients. It aims to provide a "single source of truth" for the user's music library, regardless of where the files are physically located.

## Architecture

### High-Level Architecture
The system uses a **hexagonal architecture** pattern:
- **API Layer (main.py)**: Exposes RESTful endpoints.
- **Logic Layer (indexer, watcher, services)**: Handles business logic for library management.
- **Data Layer (models, db)**: Manages persistence using SQLModel and SQLite.

### Component Design
- **Indexer**: Scans local files, extracts ID3 tags using Mutagen, and persists them.
- **Watcher**: Uses `watchdog` to monitor filesystem events and trigger the indexer incrementally.
- **Streamer**: A proxy that pipes `yt-dlp` output to a FastAPI response while simultaneously writing to a local cache file.
- **AI Shuffle** (`services/ai_shuffle.py`): Sends a listening-history prompt to the Groq LLM; parses JSON track suggestions and resolves each via YouTube Music search.
- **Melody Identification** (`services/ai_identify.py`): Sends raw audio bytes inline to Google Gemini multimodal API and parses the JSON identification result. Uses `asyncio.to_thread` to keep the blocking SDK call off the event loop.

## Data Flow
- **Search Flow**: Incoming query triggers a parallel search in the local DB and the YouTube Music API. Results are merged and deduplicated.
- **Streaming Flow**: If a track is cached, serve directly. Otherwise, stream from YouTube and cache in background.
- **AI Shuffle Flow**: Client sends context track IDs → backend builds a listening-history prompt → Groq returns `[{artist, title}]` → backend resolves each via `search_youtube` → returns resolved `Track` objects.
- **Hum-to-Search Flow**: Client records 10 s of audio → uploads multipart to `POST /ai/identify` → backend sends audio inline to Gemini → Gemini returns `{artist, title, confidence}` → backend searches YouTube for the result and returns `{artist, title, confidence, remote_id, thumbnail}`.

## Design Decisions
- **SQLModel**: Chosen for its seamless integration with FastAPI and standard Pydantic models.
- **Streaming Proxy**: Decided to proxy YouTube streams to enable caching on the server side, reducing bandwidth usage for repeat plays and allowing offline access.
- **Guest Mode YTMusic**: Initial implementation uses guest mode to avoid complex browser-based authentication for the end user.
- **Inline audio for Gemini**: Audio is sent as inline bytes in `generate_content` rather than via the Gemini File API, eliminating temp-file lifecycle complexity on constrained hardware (Raspberry Pi).
- **Groq for AI Shuffle**: Chosen for its generous free tier (~14,400 req/day), OpenAI-compatible API, and sub-second inference latency — important for seamless queue continuation UX.

## Integration Patterns
- **User Activity Scoping**: Likes and play counts are stored per user ID to support multi-user scenarios with a shared music library.
- **Rate Limiting** (`slowapi`): Applied per-user on sensitive or quota-bound endpoints — 3/min on `/ai/identify`, 10/min on `/tracks/ai-shuffle`.
