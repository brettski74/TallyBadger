from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TALLYBADGER_",
        env_file=".env",
        extra="ignore",
    )

    database_url: str = (
        "postgresql://tallybadger:tallybadger@127.0.0.1:5432/tallybadger"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
