# Requirements

## Python Dependencies
- `fastapi` >= 0.100.0
- `sqlmodel` >= 0.0.8
- `pydantic-settings` >= 2.0.0
- `python-jose` >= 3.3.0 (with [cryptography])
- `passlib` >= 1.7.4 (with [bcrypt])
- `ytmusicapi` >= 1.2.0
- `yt-dlp` >= 2023.7.6
- `mutagen` >= 1.46.0
- `watchdog` >= 3.0.0

## External Dependencies
- **YouTube Music**: For external search and streaming sources.
- **MP3 Files**: Local music collection stored in `/app/library`.

## External Services
- **Google OAuth2**: Required for secondary authentication method.
- **Cloudflare Tunnel**: For secure exposure of the local API.

## System Requirements
- **Memory**: Minimum 512MB RAM for indexing and streaming.
- **CPU**: Multi-core recommended for background indexing and concurrent searches.
- **Storage**: Sufficient space for the SQLite database and track caching in `/app/cache`.

## Security Requirements
- **JWT Authentication**: All sensitive endpoints require a Bearer token.
- **Environment Variables**: Sensitive keys (Google, JWT) must be stored in `.env`.
- **Encryption**: Passwords must be hashed using bcrypt.

## Performance Requirements
- **Search Latency**: MERGED search results should return within 1-2 seconds.
- **Stream Start**: Audio playback should begin within 500ms of the request.
