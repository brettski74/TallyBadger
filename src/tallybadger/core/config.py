from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ScanBackendKind = Literal["stub", "hplip"]
PdfPageSizeKind = Literal["us-letter", "a4"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TALLYBADGER_",
        env_file=".env",
        extra="ignore",
    )

    database_url: str = (
        "postgresql://tallybadger:tallybadger@127.0.0.1:5432/tallybadger"
    )
    frontend_host: str = "127.0.0.1"
    frontend_port: int = 5173
    cors_allowed_origins: list[str] = []
    scan_backend: ScanBackendKind = "stub"
    scanner_device_uri: str | None = None
    pdf_page_size: PdfPageSizeKind = "us-letter"

    def resolved_cors_allowed_origins(self) -> list[str]:
        if self.cors_allowed_origins:
            return self.cors_allowed_origins
        return [
            f"http://{self.frontend_host}:{self.frontend_port}",
            f"http://localhost:{self.frontend_port}",
            f"http://[::1]:{self.frontend_port}",
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
