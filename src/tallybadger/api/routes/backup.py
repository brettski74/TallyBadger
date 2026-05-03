"""Backup export / restore API (#67, #68)."""

from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile, status
from psycopg import errors as pg_errors

from tallybadger.backup.errors import (
    IncompleteSnapshotError,
    SchemaVersionMismatchError,
    SnapshotIntegrityError,
    SnapshotValidationError,
    TargetNotEmptyError,
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
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="tallybadger-backup.zip"'},
    )


@router.post("/import", status_code=status.HTTP_200_OK)
async def backup_import(
    snapshot: UploadFile = File(...),
    duplicate_policy: Literal["abort", "overwrite"] = Form(
        "abort",
        description="abort: target tables in snapshot scope must be empty; overwrite: replace scope first.",
    ),
) -> dict[str, str]:
    raw = await snapshot.read()
    try:
        with get_connection() as conn:
            import_snapshot(conn, raw, duplicate_policy=duplicate_policy)
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
    except pg_errors.ForeignKeyViolation as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"import failed: foreign key violation ({exc.diag.message_detail or exc})",
        ) from exc
    return {"status": "imported"}
