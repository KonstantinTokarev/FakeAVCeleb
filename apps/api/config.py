from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./data/jobs.db"
    redis_url: str = "redis://localhost:6379/0"
    storage_path: Path = Path("./data/storage")
    job_ttl_hours: int = 24
    max_upload_bytes: int = 209_715_200  # 200 MB
    max_video_seconds: int = 300  # 5 min
    # Comma-separated list of allowed CORS origins.
    # In production set ALLOWED_ORIGINS=https://yourdomain.com
    allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
