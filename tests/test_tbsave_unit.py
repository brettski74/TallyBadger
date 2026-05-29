"""Unit tests for standalone scripts/tbsave (#215)."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TBSAVE_PATH = REPO_ROOT / "scripts" / "tbsave"


def _load_tbsave():
    loader = importlib.machinery.SourceFileLoader("tbsave_test_module", str(TBSAVE_PATH))
    spec = importlib.util.spec_from_loader("tbsave_test_module", loader)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["tbsave_test_module"] = module
    spec.loader.exec_module(module)
    return module


tbsave = _load_tbsave()


@pytest.mark.parametrize(
    ("raw", "query_value", "canonical"),
    [
        ("complete", "complete", "complete"),
        ("full", "full", "complete"),
        ("fu", "complete", "complete"),
        ("conf", "configuration", "configuration"),
        ("configuration", "configuration", "configuration"),
        ("fi", "financial", "financial"),
        ("financial", "financial", "financial"),
    ],
)
def test_tbsave_resolve_export_scope_accepts(raw: str, query_value: str, canonical: str) -> None:
    assert tbsave.resolve_export_scope(raw) == (query_value, canonical)


@pytest.mark.parametrize("raw", ["f", "c", "g", ""])
def test_tbsave_resolve_export_scope_rejects(raw: str) -> None:
    with pytest.raises(tbsave.TbsaveError):
        tbsave.resolve_export_scope(raw)


def test_tbsave_build_base_url_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TALLYBADGER_API_BASE_URL", "http://api.example:9000")
    assert tbsave.build_base_url(base_url=None, host="127.0.0.1", port=8080) == "http://api.example:9000"


def test_tbsave_default_zip_filename_pattern(monkeypatch: pytest.MonkeyPatch) -> None:
    class FixedDatetime:
        @classmethod
        def now(cls):
            from datetime import datetime

            return datetime(2026, 5, 27, 14, 30, 45)

    monkeypatch.setattr(tbsave, "datetime", FixedDatetime)
    assert tbsave.default_zip_filename("complete") == "tallybadger-complete-20260527-143045.zip"
    assert tbsave.default_zip_filename("configuration") == "tallybadger-config-20260527-143045.zip"
    assert tbsave.default_zip_filename("financial") == "tallybadger-financial-20260527-143045.zip"


def test_tbsave_resolve_output_target_directory(tmp_path: Path) -> None:
    out_dir = tmp_path / "exports"
    out_dir.mkdir()
    target = tbsave.resolve_output_target(
        str(out_dir),
        canonical_scope="configuration",
        force=False,
        quiet=True,
    )
    assert target is not None
    assert target.parent == out_dir
    assert target.name.startswith("tallybadger-config-")
    assert target.suffix == ".zip"


def test_tbsave_resolve_output_target_rejects_missing_parent(tmp_path: Path) -> None:
    with pytest.raises(tbsave.TbsaveError, match="parent directory does not exist"):
        tbsave.resolve_output_target(
            str(tmp_path / "missing" / "snap.zip"),
            canonical_scope="complete",
            force=False,
            quiet=True,
        )


def test_tbsave_resolve_output_target_rejects_non_file_non_dir(tmp_path: Path) -> None:
    fifo = tmp_path / "fifo"
    try:
        os.mkfifo(fifo)
    except OSError as exc:
        pytest.skip(f"FIFO not supported on this platform: {exc}")
    with pytest.raises(tbsave.TbsaveError, match="neither a regular file nor a directory"):
        tbsave.resolve_output_target(
            str(fifo),
            canonical_scope="complete",
            force=False,
            quiet=True,
        )


def test_tbsave_confirm_overwrite_non_tty_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "existing.zip"
    path.write_bytes(b"old")
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(tbsave.TbsaveError, match="--force"):
        tbsave.confirm_overwrite(path)


def test_tbsave_resolve_output_target_force_skips_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "existing.zip"
    path.write_bytes(b"old")
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    target = tbsave.resolve_output_target(
        str(path),
        canonical_scope="complete",
        force=True,
        quiet=True,
    )
    assert target == path


def test_tbsave_resolve_output_target_tty_decline_cancels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "existing.zip"
    path.write_bytes(b"old")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    with pytest.raises(SystemExit):
        tbsave.resolve_output_target(
            str(path),
            canonical_scope="complete",
            force=False,
            quiet=True,
        )
    captured = capsys.readouterr()
    assert "export cancelled" in captured.err


def test_tbsave_warn_on_overwrite_unless_quiet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "existing.zip"
    path.write_bytes(b"old")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: "y")
    tbsave.resolve_output_target(
        str(path),
        canonical_scope="complete",
        force=False,
        quiet=False,
    )
    captured = capsys.readouterr()
    assert "warning: overwriting" in captured.err


def test_tbsave_info_quiet_suppresses_output(capsys: pytest.CaptureFixture[str]) -> None:
    tbsave._info("hello progress", quiet=True)
    captured = capsys.readouterr()
    assert captured.err == ""


def test_tbsave_extract_api_error_detail_from_fastapi_json() -> None:
    body = '{"detail":"unrecognized export_type \'g\'"}'
    assert "unrecognized" in (tbsave.extract_api_error_detail(body) or "")
