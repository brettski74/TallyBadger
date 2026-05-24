"""Unit tests for standalone scripts/tbload (#206)."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TBLOAD_PATH = REPO_ROOT / "scripts" / "tbload"


def _load_tbload():
    loader = importlib.machinery.SourceFileLoader("tbload_test_module", str(TBLOAD_PATH))
    spec = importlib.util.spec_from_loader("tbload_test_module", loader)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["tbload_test_module"] = module
    spec.loader.exec_module(module)
    return module


tbload = _load_tbload()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a", "abort"),
        ("abort", "abort"),
        ("e", "erase-reload"),
        ("erase-reload", "erase-reload"),
    ],
)
def test_tbload_resolve_restore_mode_accepts(raw: str, expected: str) -> None:
    assert tbload.resolve_restore_mode(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "z", "erase-spice-girls-music", "erase_reload", "overwrite-extra"],
)
def test_tbload_resolve_restore_mode_rejects(raw: str) -> None:
    with pytest.raises(tbload.TbloadError):
        tbload.resolve_restore_mode(raw)


def test_tbload_build_base_url_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TALLYBADGER_API_BASE_URL", "http://api.example:9000/")
    assert tbload.build_base_url(base_url=None, host="127.0.0.1", port=8080) == "http://api.example:9000"


def test_tbload_read_stdin_snapshot_reads_piped_data() -> None:
    read_fd, write_fd = os.pipe()
    payload = b"PK\x03\x04fake-zip"
    os.write(write_fd, payload)
    os.close(write_fd)
    sys.stdin = os.fdopen(read_fd, "rb", closefd=True)
    assert tbload.read_stdin_snapshot(timeout_seconds=1.0) == payload


def test_tbload_read_stdin_snapshot_rejects_empty_input() -> None:
    read_fd, write_fd = os.pipe()
    os.close(write_fd)
    sys.stdin = os.fdopen(read_fd, "rb", closefd=True)
    with pytest.raises(tbload.TbloadError, match="empty snapshot"):
        tbload.read_stdin_snapshot(timeout_seconds=1.0)


def test_tbload_read_stdin_snapshot_times_out_when_no_input() -> None:
    read_fd, write_fd = os.pipe()
    sys.stdin = os.fdopen(read_fd, "rb", closefd=True)
    started = time.monotonic()
    try:
        with pytest.raises(tbload.TbloadError, match="no input received"):
            tbload.read_stdin_snapshot(timeout_seconds=0.05)
    finally:
        os.close(write_fd)
    assert time.monotonic() - started < 1.0


def test_tbload_info_prints_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    tbload._info("hello progress", quiet=False)
    captured = capsys.readouterr()
    assert captured.err == "hello progress\n"
    assert captured.out == ""


def test_tbload_info_quiet_suppresses_output(capsys: pytest.CaptureFixture[str]) -> None:
    tbload._info("hello progress", quiet=True)
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == ""


def test_tbload_parse_args_quiet() -> None:
    args = tbload.parse_args(["-q", "-i", "/tmp/snap.zip"])
    assert args.quiet is True
    assert args.input == "/tmp/snap.zip"


def test_tbload_parse_args_timeout() -> None:
    assert tbload.parse_args([]).timeout is None
    assert tbload.parse_args(["-t", "5"]).timeout == 5.0
    assert tbload.parse_args(["--timeout", "12.5"]).timeout == 12.5


def test_tbload_warns_when_timeout_given_with_file(capsys: pytest.CaptureFixture[str]) -> None:
    tbload.maybe_warn_timeout_ignored_for_file_input(
        input_path="/tmp/snap.zip",
        timeout_specified=True,
    )
    captured = capsys.readouterr()
    assert "warning:" in captured.err
    assert "standard input" in captured.err
    assert "ignored" in captured.err


def test_tbload_no_timeout_warning_for_stdin(capsys: pytest.CaptureFixture[str]) -> None:
    tbload.maybe_warn_timeout_ignored_for_file_input(
        input_path=None,
        timeout_specified=True,
    )
    assert capsys.readouterr().err == ""


def test_tbload_no_timeout_warning_for_file_without_timeout_flag(
    capsys: pytest.CaptureFixture[str],
) -> None:
    tbload.maybe_warn_timeout_ignored_for_file_input(
        input_path="/tmp/snap.zip",
        timeout_specified=False,
    )
    assert capsys.readouterr().err == ""


def test_tbload_extract_api_error_detail_from_fastapi_json() -> None:
    body = json.dumps({"detail": "Snapshot import — database duplicate key (unique/PK): id=1"})
    assert tbload.extract_api_error_detail(body) == (
        "Snapshot import — database duplicate key (unique/PK): id=1"
    )


def test_tbload_format_import_http_error_surfaces_server_detail_for_409_abort() -> None:
    body = json.dumps(
        {
            "detail": (
                "Snapshot import — database duplicate key (unique/PK): "
                "Key (id)=(1) already exists.; constraint=accounts_pkey; table=accounts"
            )
        }
    )
    message = tbload.format_import_http_error(409, body, restore_mode="abort")
    assert "Import failed (HTTP 409)" in message
    assert "duplicate keys or schema version mismatch" in message
    assert "Server: Snapshot import — database duplicate key" in message
    assert "--mode erase-reload" in message
    assert "make dbclean" in message


def test_tbload_format_import_http_error_schema_mismatch_hint() -> None:
    body = json.dumps(
        {
            "detail": (
                "snapshot has '016_foo', this database has '015_bar' "
                "(snapshot is newer than this database; apply migrations or use an older release)"
            )
        }
    )
    message = tbload.format_import_http_error(409, body, restore_mode="abort")
    assert "Server: snapshot has '016_foo'" in message
    assert "tallybadger-migrate" in message
    assert "--mode erase-reload" not in message


def test_tbload_parse_curl_import_response() -> None:
    raw = b'{"status":"imported"}\n200'
    body, status = tbload.parse_curl_import_response(raw)
    assert body == '{"status":"imported"}'
    assert status == 200
