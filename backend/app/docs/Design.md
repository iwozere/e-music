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

## Data Flow
- **Search Flow**: Incoming query triggers a parallel search in the local DB and the YouTube Music API. Results are merged and deduplicated.
- **Streaming Flow**: If a track is cached, serve directly. Otherwise, stream from YouTube and cache in background.

## Design Decisions
- **SQLModel**: Chosen for its seamless integration with FastAPI and standard Pydantic models.
- **Streaming Proxy**: Decided to proxy YouTube streams to enable caching on the server side, reducing bandwidth usage for repeat plays and allowing offline access.
- **Guest Mode YTMusic**: Initial implementation uses guest mode to avoid complex browser-based authentication for the end user.

## Integration Patterns
- **User Activity Scoping**: Likes and play counts are stored per user ID to support multi-user scenarios with a shared music library.
