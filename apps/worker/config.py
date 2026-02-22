from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./data/jobs.db"
    redis_url: str = "redis://localhost:6379/0"
    storage_path: Path = Path("./data/storage")
    max_video_bytes: int = 209_715_200
    max_video_seconds: int = 300
    # Set to "true" to use real A/V model (CLIP ViT-L/14, auto-downloads from HuggingFace)
    av_model_enabled: bool = True
    # Optional: path to FakeAVCeleb repo (must contain checkpoint.pt) for video-only Xception model
    fakeavceleb_repo_dir: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
