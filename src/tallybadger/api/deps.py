"""Shared FastAPI dependencies."""

from functools import lru_cache

from tallybadger.scanner.backend import ScanBackend, get_scan_backend


@lru_cache
def get_scan_backend_dep() -> ScanBackend:
    return get_scan_backend()
