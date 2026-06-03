"""Unit tests for scanner filename and stub backend."""

from datetime import date

from tallybadger.scanner.filename import build_scan_filename, to_kebab_segment
from tallybadger.scanner.hplip import scanimage_flatbed_command
from tallybadger.scanner.stub import StubScanBackend, minimal_jpeg_bytes
from tallybadger.scanner.backend import ScanSettings


def test_to_kebab_segment() -> None:
    assert to_kebab_segment("Acme Plumbing") == "acme-plumbing"
    assert to_kebab_segment("  Invoice — May 2026!  ") == "invoice-may-2026"
    assert to_kebab_segment("---") == "unknown"


def test_build_scan_filename() -> None:
    name = build_scan_filename(
        entry_date=date(2026, 5, 30),
        party_name="Acme Plumbing",
        summary="Invoice May",
    )
    assert name == "20260530.acme-plumbing.invoice-may.jpg"


def test_scanimage_flatbed_command_geometry() -> None:
    cmd = scanimage_flatbed_command("hpaio:/example", dpi=300, color_mode="greyscale")
    assert "-l" in cmd and "0" in cmd
    assert "-x" in cmd and "215.9mm" in cmd
    assert "-y" in cmd and "279.4mm" in cmd
    assert "--page-width" not in cmd


def test_stub_scan_backend_returns_jpeg() -> None:
    backend = StubScanBackend()
    data = backend.scan_flatbed(
        ScanSettings(device_uri=None, dpi=300, color_mode="greyscale", env_device_uri=None),
    )
    assert data.startswith(b"\xff\xd8")
    assert data.endswith(b"\xff\xd9")
    assert data == minimal_jpeg_bytes()
