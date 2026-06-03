"""Scan backend protocol and factory."""

from dataclasses import dataclass
from typing import Literal, Protocol

from tallybadger.core.config import get_settings


@dataclass(frozen=True)
class ScanSettings:
    device_uri: str | None
    dpi: int
    color_mode: str
    env_device_uri: str | None

    def resolved_device_uri(self) -> str | None:
        if self.env_device_uri and self.env_device_uri.strip():
            return self.env_device_uri.strip()
        if self.device_uri and self.device_uri.strip():
            return self.device_uri.strip()
        return None


class ScanBackend(Protocol):
    def scan_flatbed(self, settings: ScanSettings) -> bytes:
        """Capture one flatbed page as JPEG bytes."""


ScanBackendKind = Literal["stub", "hplip"]


def resolve_scan_backend_kind(settings: ScanSettings | None = None) -> ScanBackendKind:
    """Pick stub vs HPLIP for this request.

    Explicit ``TALLYBADGER_SCAN_BACKEND`` (including via ``.env``) always wins.
    Otherwise use HPLIP when a device URI is configured in ledger settings or env.
    """
    app = get_settings()
    if "scan_backend" in app.model_fields_set:
        return app.scan_backend
    if settings and settings.resolved_device_uri():
        return "hplip"
    return "stub"


def get_scan_backend_for_settings(
    settings: ScanSettings | None = None,
    *,
    kind: ScanBackendKind | None = None,
) -> ScanBackend:
    from tallybadger.scanner.hplip import HplipScanBackend
    from tallybadger.scanner.stub import StubScanBackend

    resolved = kind or resolve_scan_backend_kind(settings)
    if resolved == "hplip":
        return HplipScanBackend()
    return StubScanBackend()


def get_scan_backend(kind: ScanBackendKind | None = None) -> ScanBackend:
    return get_scan_backend_for_settings(None, kind=kind)
