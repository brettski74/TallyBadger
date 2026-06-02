"""Backup export / restore API (#67, #68, #252)."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request, status
from psycopg import errors as pg_errors
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse

from tallybadger.backup.errors import (
    IncompleteSnapshotError,
    SchemaVersionMismatchError,
    SnapshotIntegrityError,
    SnapshotValidationError,
    UnsupportedFormatVersionError,
)
from tallybadger.backup.export_type import ExportTypeError, normalize_export_type
from tallybadger.backup.restore_mode import RestoreModeError, resolve_restore_mode
from tallybadger.backup.snapshot import (
    detect_snapshot_container,
    import_snapshot,
    import_snapshot_from_gzip_stream,
    iter_export_snapshot,
)
from tallybadger.db import get_connection

router = APIRouter(prefix="/backup", tags=["backup"])

_RAW_IMPORT_MEDIA_TYPES = frozenset(
    {
        "application/gzip",
        "application/x-gzip",
        "application/octet-stream",
        "application/zip",
    }
)


def _postgres_import_detail(exc: pg_errors.Error) -> str:
    """Human-oriented context for snapshot import DB failures."""
    diag = exc.diag
    parts: list[str] = []
    if diag.message_detail:
        parts.append(str(diag.message_detail))
    elif str(exc):
        parts.append(str(exc))
    if diag.constraint_name:
        parts.append(f"constraint={diag.constraint_name}")
    if diag.table_name:
        parts.append(f"table={diag.table_name}")
    if diag.column_name:
        parts.append(f"column={diag.column_name}")
    return "; ".join(parts) if parts else str(exc)


def _map_import_exception(exc: Exception) -> HTTPException:
    if isinstance(exc, UnsupportedFormatVersionError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if isinstance(exc, IncompleteSnapshotError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if isinstance(exc, SnapshotIntegrityError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if isinstance(exc, SnapshotValidationError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if isinstance(exc, SchemaVersionMismatchError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, pg_errors.UniqueViolation):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Snapshot import — database duplicate key (unique/PK): "
                f"{_postgres_import_detail(exc)}"
            ),
        )
    if isinstance(exc, pg_errors.ForeignKeyViolation):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Snapshot import — database foreign key violation: "
                f"{_postgres_import_detail(exc)}"
            ),
        )
    if isinstance(exc, pg_errors.CheckViolation):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Snapshot import — database check constraint failed: "
                f"{_postgres_import_detail(exc)}"
            ),
        )
    if isinstance(exc, pg_errors.NotNullViolation):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Snapshot import — database NOT NULL violation: "
                f"{_postgres_import_detail(exc)}"
            ),
        )
    raise exc


def _import_body(*, format_warning: str | None) -> dict[str, str]:
    body: dict[str, str] = {"status": "imported"}
    if format_warning is not None:
        body["format_deprecation_warning"] = format_warning
    return body


def _run_import_bytes(archive_bytes: bytes, restore_mode: str) -> dict[str, str]:
    try:
        with get_connection() as conn:
            format_warning = import_snapshot(conn, archive_bytes, restore_mode=restore_mode)
    except Exception as exc:
        raise _map_import_exception(exc) from exc
    return _import_body(format_warning=format_warning)


async def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    offset = 0
    while offset < len(view):
        nbytes = await run_in_threadpool(os.write, fd, view[offset:])
        if nbytes <= 0:
            raise IncompleteSnapshotError("unexpected end of snapshot upload stream")
        offset += nbytes


async def _pump_chunks_to_pipe(
    write_fd: int,
    prefix: bytes,
    stream: AsyncIterator[bytes],
) -> None:
    try:
        if prefix:
            await _write_all(write_fd, prefix)
        async for chunk in stream:
            if chunk:
                await _write_all(write_fd, chunk)
    finally:
        os.close(write_fd)


async def _import_raw_body(request: Request, restore_mode: str) -> dict[str, str]:
    """Single pass over ``request.stream()`` — detect container, then zip-buffer or gzip-pipe."""
    body_stream = request.stream()
    prefix = bytearray()
    container = None

    while container is None:
        try:
            chunk = await body_stream.__anext__()
        except StopAsyncIteration:
            if len(prefix) < 4:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "snapshot upload is empty or too small; "
                        "expected a .zip or .tar.gz backup"
                    ),
                ) from None
            try:
                container = detect_snapshot_container(bytes(prefix[:4]))
            except IncompleteSnapshotError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(exc),
                ) from exc
            break
        prefix.extend(chunk)
        if len(prefix) >= 4:
            try:
                container = detect_snapshot_container(bytes(prefix[:4]))
            except IncompleteSnapshotError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(exc),
                ) from exc
            if container == "zip":
                break

    assert container is not None

    if container == "zip":
        async for chunk in body_stream:
            prefix.extend(chunk)
        return _run_import_bytes(bytes(prefix), restore_mode)

    read_fd, write_fd = os.pipe()
    pump_task = asyncio.create_task(
        _pump_chunks_to_pipe(write_fd, bytes(prefix), body_stream),
    )

    def import_from_pipe() -> str | None:
        with os.fdopen(read_fd, "rb") as readable:
            with get_connection() as conn:
                return import_snapshot_from_gzip_stream(
                    conn,
                    readable,
                    restore_mode=restore_mode,
                )

    try:
        format_warning = await run_in_threadpool(import_from_pipe)
    except Exception as exc:
        raise _map_import_exception(exc) from exc
    finally:
        await pump_task
    return _import_body(format_warning=format_warning)


def _export_filename(export_type: str) -> str:
    stem = {
        "complete": "tallybadger-complete",
        "configuration": "tallybadger-config",
        "financial": "tallybadger-financial",
    }[export_type]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{stem}-{stamp}.tar.gz"


def _iter_export_chunks(export_type: str) -> Iterator[bytes]:
    with get_connection() as conn:
        yield from iter_export_snapshot(conn, export_type)


@router.post("/export")
def backup_export(
    export_type: str = Query(
        "complete",
        description=(
            "Snapshot scope: complete, configuration (no GL/settlements), financial only, "
            "or full (alias for complete)."
        ),
    ),
) -> StreamingResponse:
    try:
        canonical_export_type = normalize_export_type(export_type)
    except ExportTypeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    filename = _export_filename(canonical_export_type)
    return StreamingResponse(
        _iter_export_chunks(canonical_export_type),
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import", status_code=status.HTTP_200_OK)
async def backup_import(request: Request) -> dict[str, str]:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()

    if content_type.startswith("multipart/"):
        form = await request.form()
        upload = form.get("snapshot")
        if upload is None or not hasattr(upload, "read"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="multipart import requires a snapshot file field",
            )
        mode_raw = str(form.get("restore_mode", "abort"))
        try:
            canonical_mode = resolve_restore_mode(mode_raw)
        except RestoreModeError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        raw = await upload.read()
        return _run_import_bytes(raw, canonical_mode)

    if content_type not in _RAW_IMPORT_MEDIA_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "import requires multipart/form-data (legacy) or a raw snapshot body with "
                f"Content-Type one of {sorted(_RAW_IMPORT_MEDIA_TYPES)}"
            ),
        )

    mode_raw = request.query_params.get("restore_mode", "abort")
    try:
        canonical_mode = resolve_restore_mode(mode_raw)
    except RestoreModeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return await _import_raw_body(request, canonical_mode)
