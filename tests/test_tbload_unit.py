"""Unit tests for standalone scripts/tbload (#206)."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
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
