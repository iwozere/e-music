"""Environment-driven application settings (Pydantic ``BaseSettings``)."""

import os
import secrets
import warnings
from pathlib import Path
from typing import Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# --- Run profiles (see docs/features-v7.md) ---------------------------------
# "server"     — Docker / Pi deployment behind a tunnel: /app/* paths, OAuth, multi-user.
# "standalone" — self-contained desktop app on a user's own PC: loopback bind,
#                OS user-data dirs, local single-user auth, OAuth optional.
PROFILE_SERVER = "server"
PROFILE_STANDALONE = "standalone"

# Container path defaults — applied only when a path is left blank in the server profile.
_SERVER_PATH_DEFAULTS = {
    "DATABASE_URL": "sqlite:////app/db/myspotify.db",
    "MUSIC_PATH": "/app/library",
    "CACHE_DIR": "/app/cache",
    "TEMP_DIR": "/tmp/myspotify_cache",
}


def _platform_data_dir() -> Path:
    """OS-appropriate per-user data directory for the Standalone Edition."""
    try:
        from platformdirs import user_data_dir

        return Path(user_data_dir("MySpotify", "iwozere"))
    except Exception:  # platformdirs missing — degrade gracefully
        return Path.home() / ".myspotify"


def _platform_cache_dir() -> Path:
    """OS-appropriate per-user cache directory (used for the temp/LRU stream cache)."""
    try:
        from platformdirs import user_cache_dir

        return Path(user_cache_dir("MySpotify", "iwozere"))
    except Exception:
        return Path.home() / ".myspotify" / "cache"


class Settings(BaseSettings):
    """
    Application configuration settings loaded from environment variables.
    """
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    # Run profile: "server" (default, Docker/Pi) or "standalone" (self-contained desktop app).
    APP_PROFILE: str = PROFILE_SERVER
    # Root for the standalone data dir (DB, library, logs, local secret). Blank = OS default
    # via platformdirs. Ignored in the server profile.
    DATA_DIR: str = ""

    DOMAIN: str = "e-music.win"
    # OAuth / JWT are required in the server profile but optional in standalone, where a
    # local single-user account is auto-provisioned and JWT_SECRET is generated on first run.
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = ""
    JWT_SECRET: str = ""
    ALGORITHM: str = "HS256"
    # Blank by default; resolved per-profile in _apply_profile (Docker path vs. user-data dir).
    DATABASE_URL: str = ""
    # Short-lived access token (use refresh token for renewal).
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    # Comma-separated emails that always receive admin role (case-insensitive).
    ADMIN_EMAILS: str = ""
    # HMAC for signed stream URLs; defaults to JWT_SECRET if empty.
    STREAM_URL_SIGNING_SECRET: str = ""
    STREAM_URL_TTL_SECONDS: int = 600
    # Standalone "Home Remote" (docs/features-v7.md §6): when non-empty (standalone only),
    # POST /auth/pair lets a LAN device exchange this PIN for tokens. Set by the desktop
    # launcher when remote access is opted into; empty disables pairing.
    LOCAL_PAIRING_PIN: str = ""

    # Optional / Extra fields from .env. Paths default per-profile in _apply_profile when blank.
    MUSIC_PATH: str = ""
    CACHE_DIR: str = ""
    TEMP_DIR: str = ""
    # Absolute path to the ffmpeg binary. Blank = resolve from PATH / venv (server); the
    # standalone bundle points this at its vendored static ffmpeg build (docs/features-v7.md §3.3).
    FFMPEG_PATH: str = ""
    API_SUBDOMAIN: Optional[str] = None
    # e.g. https://api.example.com — used for signed stream URLs and GET /api/v1/config when
    # the app is reached via an internal URL (Docker network) but clients use a public host.
    PUBLIC_API_BASE_URL: Optional[str] = None
    # YouTube / yt-dlp: datacenter IPs are often blocked with the default web client;
    # optional Netscape cookies.txt helps. Extra args: streamer._build_yt_dlp_argv.
    YTDLP_COOKIES_FILE: Optional[str] = None
    # Comma-separated yt-dlp YouTube clients (youtube:player_client=...). The old
    # "tv_embedded" default was removed from yt-dlp in 2025; "tv" is its replacement.
    # "web" needs a JS runtime (Deno or Node 20+) in PATH to solve signature/n challenges.
    # Avoid leading with "android" unless you supply a PO token (yt-dlp YouTube docs).
    YTDLP_YOUTUBE_PLAYER_CLIENT: str = "tv,web,mweb"
    YTDLP_EXTRA_ARGS: str = ""

    # --- Streaming pipeline tuning (Feature 1: fast YouTube playback) ---
    # Low-latency ffmpeg flags (nobuffer, low_delay) + small analyzeduration/probesize.
    STREAM_LOW_LATENCY: bool = True
    # Pass-through (stream-copy) audio when the source codec is browser-safe (opus/aac).
    # When False, audio is transcoded to MP3 (legacy behavior, higher CPU + slower first byte).
    STREAM_PASSTHROUGH: bool = True
    # ffmpeg probe window (microseconds / bytes). The pre-existing default was 10_000_000.
    STREAM_ANALYZEDURATION_US: int = 500_000
    STREAM_PROBESIZE_BYTES: int = 500_000
    # Bitrate used only when transcode fallback path runs.
    STREAM_TRANSCODE_BITRATE_KBPS: int = 128
    # Resolved direct-URL cache TTL for the yt-dlp Python-API resolver. googlevideo URLs
    # typically live ~6h; keep our TTL well under that and re-resolve on 403/410.
    YTDLP_RESOLVED_URL_TTL_SEC: int = 18_000
    # Emergency kill-switch: force the legacy subprocess pipeline even when the resolver is up.
    STREAM_FORCE_LEGACY_SUBPROCESS: bool = False
    # Bytes to accumulate from ffmpeg before sending the first HTTP chunk to the browser.
    # A larger value gives the browser a bigger initial burst (more buffered audio) at the
    # cost of a slightly higher start-up latency. 0 disables pre-buffering (legacy behaviour).
    STREAM_PREBUFFER_BYTES: int = 256 * 1024
    # Size (bytes) of each sequential HTTP Range request when pulling the resolved
    # googlevideo URL. Google throttles a single non-ranged full-file GET to ~playback
    # rate (causing mid-track stalls on non-cached tracks); fetching in ranged chunks
    # resets the per-connection throttle window each request and keeps the buffer full.
    # Set to 0 to disable ranged chunking and fall back to a single streaming GET.
    STREAM_HTTP_CHUNK_BYTES: int = 1024 * 1024

    # --- AI Shuffle (Groq LLM-backed radio mode) ---
    GROQ_API_KEY: Optional[str] = None
    # Model to use; llama-3.1-8b-instant is fast and free-tier friendly.
    GROQ_MODEL: str = "llama-3.1-8b-instant"

    # --- Hum-to-Search (Gemini multimodal melody identification) ---
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-2.5-flash"
    # Minimum confidence score (0-100) to accept a Gemini identification result.
    IDENTIFY_MIN_CONFIDENCE: int = 75

    # --- Prefetch / warm-cache (Feature 2: zero-latency next-track playback) ---
    PREFETCH_ENABLED: bool = True
    # Upper bound on concurrent prefetch jobs server-wide; guards the Pi's CPU/network.
    # Pi 5 (16 GB, lightly loaded) comfortably handles 3 concurrent warm-ups, so a live
    # play that is mid-resolve never causes the next-track prefetch to be declined.
    PREFETCH_MAX_CONCURRENT: int = 3

    @model_validator(mode="after")
    def _apply_profile(self) -> "Settings":
        """Resolve profile-dependent defaults (paths, local secret) and validate secrets."""
        self.APP_PROFILE = (self.APP_PROFILE or PROFILE_SERVER).strip().lower()
        if self.APP_PROFILE == PROFILE_STANDALONE:
            self._configure_standalone()
        else:
            self._configure_server()
        self._check_jwt_secret()
        return self

    def _configure_server(self) -> None:
        """Fill blank paths with the container defaults used by the Docker/Pi deployment."""
        for key, default in _SERVER_PATH_DEFAULTS.items():
            if not getattr(self, key):
                setattr(self, key, default)

    def _configure_standalone(self) -> None:
        """Compute OS user-data paths, create them, and provision a persistent local secret."""
        data_dir = Path(self.DATA_DIR) if self.DATA_DIR else _platform_data_dir()
        cache_root = _platform_cache_dir()
        self.DATA_DIR = str(data_dir)

        db_dir = data_dir / "db"
        library_dir = data_dir / "library"
        logs_dir = data_dir / "logs"
        cache_dir = cache_root / "cache"
        temp_dir = cache_root / "temp"
        for directory in (db_dir, library_dir, logs_dir, cache_dir, temp_dir):
            try:
                directory.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                warnings.warn(f"Could not create standalone directory {directory}: {exc}", stacklevel=2)

        if not self.DATABASE_URL:
            self.DATABASE_URL = f"sqlite:///{(db_dir / 'myspotify.db').as_posix()}"
        if not self.MUSIC_PATH:
            self.MUSIC_PATH = str(library_dir)
        if not self.CACHE_DIR:
            self.CACHE_DIR = str(cache_dir)
        if not self.TEMP_DIR:
            self.TEMP_DIR = str(temp_dir)
        if not self.JWT_SECRET:
            self.JWT_SECRET = self._load_or_create_local_secret(data_dir)

    @staticmethod
    def _load_or_create_local_secret(data_dir: Path) -> str:
        """Read a persisted local JWT secret, or generate and store one on first run.

        Persisting the secret keeps standalone access/refresh tokens valid across restarts.
        Falls back to an ephemeral secret if the data dir is not writable.
        """
        key_file = data_dir / "secret.key"
        try:
            if key_file.exists():
                existing = key_file.read_text(encoding="utf-8").strip()
                if existing:
                    return existing
            secret = secrets.token_hex(32)
            key_file.write_text(secret, encoding="utf-8")
            try:
                os.chmod(key_file, 0o600)
            except OSError:
                pass  # best-effort on platforms without POSIX perms
            return secret
        except OSError:
            return secrets.token_hex(32)

    def _check_jwt_secret(self) -> None:
        """Warn on a missing/weak JWT secret without crashing (standalone generates one)."""
        value = self.JWT_SECRET or ""
        if not value:
            warnings.warn(
                "JWT_SECRET is not set — required for the server profile. Generate one with "
                "`python -c \"import secrets; print(secrets.token_hex(32))\"`",
                stacklevel=2,
            )
        elif len(value) < 32:
            warnings.warn(
                f"JWT_SECRET is only {len(value)} characters — use at least 32 random characters "
                "in production (e.g. `python -c \"import secrets; print(secrets.token_hex(32))\"`)",
                stacklevel=2,
            )

    @classmethod
    def strip_variables(cls, values: dict) -> dict:
        """Sanitize input values by stripping whitespace from all strings."""
        return {k: v.strip() if isinstance(v, str) else v for k, v in values.items()}

    def __init__(self, **values):
        """Instantiate settings from keyword arguments (typically env-backed), trimming strings."""
        super().__init__(**self.strip_variables(values))

    def is_standalone(self) -> bool:
        """True when running as the self-contained desktop app (``APP_PROFILE=standalone``)."""
        return self.APP_PROFILE == PROFILE_STANDALONE

    def ffmpeg_executable(self) -> str:
        """Resolve the ffmpeg binary; honors ``FFMPEG_PATH`` (bundled build in standalone)."""
        return (self.FFMPEG_PATH or "").strip() or "ffmpeg"

    def pairing_enabled(self) -> bool:
        """True when LAN pairing via POST /auth/pair is active (standalone + a PIN is set)."""
        return self.is_standalone() and bool(self.LOCAL_PAIRING_PIN)

    def auth_mode(self) -> str:
        """Client-facing auth mode: 'oauth' (Google configured), 'local' (standalone), or 'password'."""
        if self.GOOGLE_CLIENT_ID:
            return "oauth"
        if self.is_standalone():
            return "local"
        return "password"

    def admin_email_set(self) -> set[str]:
        """Return unique admin emails from ``ADMIN_EMAILS`` (comma-separated, lowercased)."""
        return {e.strip().lower() for e in self.ADMIN_EMAILS.split(",") if e.strip()}

    def stream_signing_secret(self) -> str:
        """Secret used to sign short-lived stream URLs; falls back to ``JWT_SECRET`` if unset."""
        return self.STREAM_URL_SIGNING_SECRET or self.JWT_SECRET


settings: Settings = Settings()
