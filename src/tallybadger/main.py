"""FastAPI application entrypoint."""

import os

import uvicorn
from fastapi import FastAPI

from tallybadger import __version__
from tallybadger.api.routes import health, ledger

app = FastAPI(
    title="TallyBadger",
    description="Double-entry accounting API for small rental portfolios.",
    version=__version__,
)

app.include_router(health.router)
app.include_router(ledger.router)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "app": "TallyBadger",
        "detail": "API is up. Ledger and property routes will mount here.",
    }


def run() -> None:
    """CLI entrypoint for `tallybadger-api` (used by Docker)."""
    host = os.environ.get("TALLYBADGER_HOST", "0.0.0.0")
    port = int(os.environ.get("TALLYBADGER_PORT", "8080"))
    uvicorn.run(
        "tallybadger.main:app",
        host=host,
        port=port,
        factory=False,
    )


if __name__ == "__main__":
    run()
