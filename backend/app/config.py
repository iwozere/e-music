from typing import Optional
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
    CLOUDFLARE_TUNNEL_TOKEN: Optional[str] = None
    # e.g. https://api.example.com — used for signed stream URLs and GET /api/v1/config when
    # the app is reached via an internal URL (Docker network) but clients use a public host.
    PUBLIC_API_BASE_URL: Optional[str] = None

    @classmethod
    def strip_variables(cls, values: dict) -> dict:
        """
        Sanitize input values by stripping whitespace from all strings.
        """
        for key, value in values.items():
            if isinstance(value, str):
                values[key] = value.strip()
        return values

    def __init__(self, **values):
        super().__init__(**self.strip_variables(values))

    def admin_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.ADMIN_EMAILS.split(",") if e.strip()}

    def stream_signing_secret(self) -> str:
        return self.STREAM_URL_SIGNING_SECRET or self.JWT_SECRET


settings: Settings = Settings()
