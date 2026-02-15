from typing import Optional
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """
    Application configuration settings loaded from environment variables.
    """
    DOMAIN: str = "e-music.win"
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str
    GOOGLE_REDIRECT_URI: str
    JWT_SECRET: str
    ALGORITHM: str = "HS256"
    DATABASE_URL: str = "sqlite:////app/db/myspotify.db"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 43200  # 30 days
    
    # Optional / Extra fields from .env
    MUSIC_PATH: str = "/app/library"
    CACHE_DIR: str = "/app/cache"
    TEMP_DIR: str = "/tmp/myspotify_cache"
    API_SUBDOMAIN: Optional[str] = None
    CLOUDFLARE_TUNNEL_TOKEN: Optional[str] = None

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
    
    class Config:
        """
        Pydantic config for loading .env file.
        """
        env_file = (
            ".env",
            "../.env"
        )
        extra = "ignore"

settings: Settings = Settings()
