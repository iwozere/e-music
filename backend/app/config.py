"""Environment-driven application settings (Pydantic ``BaseSettings``)."""

import warnings
from typing import Optional
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application configuration settings loaded from environment variables.
    """
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    DOMAIN: str = "e-music.win"
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str
    GOOGLE_REDIRECT_URI: str
    JWT_SECRET: str
    ALGORITHM: str = "HS256"
    DATABASE_URL: str = "sqlite:////app/db/myspotify.db"
    # Short-lived access token (use refresh token for renewal).
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    # Comma-separated emails that always receive admin role (case-insensitive).
    ADMIN_EMAILS: str = ""
    # HMAC for signed stream URLs; defaults to JWT_SECRET if empty.
    STREAM_URL_SIGNING_SECRET: str = ""
    STREAM_URL_TTL_SECONDS: int = 600

    # Optional / Extra fields from .env
    MUSIC_PATH: str = "/app/library"
    CACHE_DIR: str = "/app/cache"
    TEMP_DIR: str = "/tmp/myspotify_cache"
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
    PREFETCH_MAX_CONCURRENT: int = 2

    @field_validator("JWT_SECRET")
    @classmethod
    def jwt_secret_strength(cls, v: str) -> str:
        if len(v) < 32:
            warnings.warn(
                f"JWT_SECRET is only {len(v)} characters — use at least 32 random characters "
                "in production (e.g. `python -c \"import secrets; print(secrets.token_hex(32))\"`)",
                stacklevel=2,
            )
        return v

    @classmethod
    def strip_variables(cls, values: dict) -> dict:
        """Sanitize input values by stripping whitespace from all strings."""
        return {k: v.strip() if isinstance(v, str) else v for k, v in values.items()}

    def __init__(self, **values):
        """Instantiate settings from keyword arguments (typically env-backed), trimming strings."""
        super().__init__(**self.strip_variables(values))

    def admin_email_set(self) -> set[str]:
        """Return unique admin emails from ``ADMIN_EMAILS`` (comma-separated, lowercased)."""
        return {e.strip().lower() for e in self.ADMIN_EMAILS.split(",") if e.strip()}

    def stream_signing_secret(self) -> str:
        """Secret used to sign short-lived stream URLs; falls back to ``JWT_SECRET`` if unset."""
        return self.STREAM_URL_SIGNING_SECRET or self.JWT_SECRET


settings: Settings = Settings()
