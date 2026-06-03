"""Flatbed scan via ``scanimage`` (SANE/HPLIP)."""

import subprocess
import tempfile
from pathlib import Path
from typing import Final

from tallybadger.scanner.backend import ScanBackend, ScanSettings
from tallybadger.scanner.errors import ScannerError

# Fixed flatbed area: US Letter width; height below device default max (296.926mm) per #258.
_SCAN_AREA_LEFT_MM: Final = "0"
_SCAN_AREA_TOP_MM: Final = "0"
_SCAN_AREA_WIDTH_MM: Final = "215.9mm"
_SCAN_AREA_HEIGHT_MM: Final = "279.4mm"
_SCAN_TIMEOUT_SECONDS: Final = 120


def scanimage_flatbed_command(
    device: str,
    *,
    dpi: int,
    color_mode: str,
    output_path: str | Path,
) -> list[str]:
    """Build ``scanimage`` argv for one flatbed JPEG (geometry: -l -t -x -y)."""
    mode = "Gray" if color_mode == "greyscale" else color_mode
    return [
        "scanimage",
        "-d",
        device,
        "--source",
        "Flatbed",
        "--mode",
        mode,
        "--resolution",
        str(dpi),
        "-l",
        _SCAN_AREA_LEFT_MM,
        "-t",
        _SCAN_AREA_TOP_MM,
        "-x",
        _SCAN_AREA_WIDTH_MM,
        "-y",
        _SCAN_AREA_HEIGHT_MM,
        "--format=jpeg",
        "--output",
        str(output_path),
    ]


class HplipScanBackend(ScanBackend):
    def scan_flatbed(self, settings: ScanSettings) -> bytes:
        device = settings.resolved_device_uri()
        if not device:
            raise ScannerError(
                "scanner device URI is not configured "
                "(set ledger_settings.scanner_device_uri or TALLYBADGER_SCANNER_DEVICE_URI)",
            )

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            output_path = Path(tmp.name)

        cmd = scanimage_flatbed_command(
            device,
            dpi=settings.dpi,
            color_mode=settings.color_mode,
            output_path=output_path,
        )
        try:
            try:
                completed = subprocess.run(
                    cmd,
                    check=False,
                    capture_output=True,
                    timeout=_SCAN_TIMEOUT_SECONDS,
                )
            except FileNotFoundError as exc:
                raise ScannerError("scanimage is not installed or not on PATH") from exc
            except subprocess.TimeoutExpired as exc:
                raise ScannerError("scan timed out waiting for the flatbed") from exc

            if completed.returncode != 0:
                stderr = completed.stderr.decode("utf-8", errors="replace").strip()
                stdout = completed.stdout.decode("utf-8", errors="replace").strip()
                detail = stderr or stdout or f"exit code {completed.returncode}"
                raise ScannerError(f"scanimage failed: {detail}")

            if not output_path.is_file():
                stderr = completed.stderr.decode("utf-8", errors="replace").strip()
                detail = stderr or "output file was not created"
                raise ScannerError(f"scanimage returned no image data: {detail}")

            data = output_path.read_bytes()
            if not data:
                raise ScannerError("scanimage wrote an empty file")
            return data
        finally:
            output_path.unlink(missing_ok=True)
