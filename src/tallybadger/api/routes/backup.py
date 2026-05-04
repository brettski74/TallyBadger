"""Backup export / restore API (#67, #68)."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile, status
from psycopg import errors as pg_errors

from tallybadger.backup.errors import (
    IncompleteSnapshotError,
    SchemaVersionMismatchError,
    SnapshotIntegrityError,
    SnapshotValidationError,
    UnsupportedFormatVersionError,
)
from tallybadger.backup.snapshot import export_snapshot, import_snapshot
from tallybadger.db import get_connection

router = APIRouter(prefix="/backup", tags=["backup"])


@router.post("/export", response_class=Response)
def backup_export(
    export_type: Literal["complete", "configuration", "financial"] = Query(
        "complete",
        description="Snapshot scope: complete, configuration (no GL/settlements), or financial only.",
    ),
) -> Response:
    with get_connection() as conn:
        data = export_snapshot(conn, export_type)
    stem = {
        "complete": "tallybadger-complete",
        "configuration": "tallybadger-config",
        "financial": "tallybadger-financial",
    }[export_type]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"{stem}-{stamp}.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import", status_code=status.HTTP_200_OK)
async def backup_import(
    snapshot: UploadFile = File(...),
    restore_mode: Literal["abort", "overwrite", "erase_reload"] = Form(
        "abort",
        description="Per-request only: abort, overwrite, or erase_reload. Not stored in the backup file.",
    ),
) -> dict[str, str]:
    raw = await snapshot.read()
    try:
        with get_connection() as conn:
            import_snapshot(conn, raw, restore_mode=restore_mode)
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
    except pg_errors.UniqueViolation as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"import aborted: duplicate key or unique constraint ({exc.diag.message_detail or exc})",
        ) from exc
    except pg_errors.ForeignKeyViolation as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"import failed: foreign key violation ({exc.diag.message_detail or exc})",
        ) from exc
    return {"status": "imported"}
