"""FastAPI application entrypoint."""

import os

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from tallybadger import __version__
from tallybadger.api.routes import (
    backup,
    cel_rule_sets,
    cheque_register_filter_presets,
    cheques,
    health,
    import_csv,
    import_rules_cel,
    import_templates,
    journal_entry_filter_presets,
    ledger,
    reports,
)
from tallybadger.core.config import get_settings

app = FastAPI(
    title="TallyBadger",
    description="Double-entry accounting API for small rental portfolios.",
    version=__version__,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.resolved_cors_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(backup.router)
app.include_router(cheques.router)
app.include_router(cheque_register_filter_presets.router)
app.include_router(health.router)
app.include_router(import_rules_cel.router)
app.include_router(cel_rule_sets.router)
app.include_router(import_templates.router)
app.include_router(import_csv.router)
app.include_router(journal_entry_filter_presets.router)
app.include_router(ledger.router)
app.include_router(reports.router)


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
