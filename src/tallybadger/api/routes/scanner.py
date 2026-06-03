"""Server-side flatbed scan API."""

import io

from fastapi import APIRouter, Depends, HTTPException, status
from starlette.responses import StreamingResponse

from tallybadger.api.routes.ledger import get_scan_backend_dep
from tallybadger.api.routes.ledger import get_ledger_service
from tallybadger.ledger.service import LedgerService, ScannerIntegrationError
from tallybadger.scanner.backend import ScanBackend

router = APIRouter(prefix="", tags=["scanner"])


@router.post("/scanner/flatbed")
def scan_flatbed(
    service: LedgerService = Depends(get_ledger_service),
    scan_backend: ScanBackend = Depends(get_scan_backend_dep),
) -> StreamingResponse:
    try:
        jpeg = service.scan_flatbed_jpeg(scan_backend=scan_backend)
    except ScannerIntegrationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return StreamingResponse(io.BytesIO(jpeg), media_type="image/jpeg")
