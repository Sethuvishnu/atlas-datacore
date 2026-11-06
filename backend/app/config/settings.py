"""Application configuration, loaded from environment variables / .env."""
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", ".env"),
        env_prefix="DATACORE_",
        extra="ignore",
    )

    environment: str = Field("local", description="local | staging | production")
    database_url: str = "postgresql+psycopg://datacore:datacore@localhost:5432/datacore"
    log_level: str = "INFO"
    log_json: bool = False
    data_dir: Path = PROJECT_ROOT / "data"
    # Enforced for non-local deployments when the API milestone lands.
    api_key: str | None = None

    @property
    def is_local(self) -> bool:
        return self.environment == "local"


@lru_cache
def get_settings() -> Settings:
    return Settings()
