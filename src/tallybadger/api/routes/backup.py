"""Backup export / restore API (#67)."""

from fastapi import APIRouter, File, HTTPException, Response, UploadFile, status

from tallybadger.backup.errors import (
    IncompleteSnapshotError,
    SchemaVersionMismatchError,
    SnapshotIntegrityError,
    SnapshotValidationError,
    TargetNotEmptyError,
    UnsupportedFormatVersionError,
)
from tallybadger.backup.snapshot import export_complete_snapshot, import_complete_snapshot
from tallybadger.db import get_connection

router = APIRouter(prefix="/backup", tags=["backup"])


@router.post("/export", response_class=Response)
def backup_export() -> Response:
    with get_connection() as conn:
        data = export_complete_snapshot(conn)
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="tallybadger-backup.zip"'},
    )


@router.post("/import", status_code=status.HTTP_200_OK)
async def backup_import(snapshot: UploadFile = File(...)) -> dict[str, str]:
    raw = await snapshot.read()
    try:
        with get_connection() as conn:
            import_complete_snapshot(conn, raw)
    except UnsupportedFormatVersionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except IncompleteSnapshotError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except SnapshotIntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except SnapshotValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except SchemaVersionMismatchError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except TargetNotEmptyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {"status": "imported"}
