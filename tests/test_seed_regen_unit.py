"""Unit tests for scripts/seed_regen (#238)."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from tallybadger.backup.snapshot import (
    _canonical_envelope_bytes,
    _pack_targz,
    export_format_version,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SEED_REGEN_PATH = REPO_ROOT / "scripts" / "seed_regen"


def _load_seed_regen():
    loader = importlib.machinery.SourceFileLoader(
        "seed_regen_test_module",
        str(SEED_REGEN_PATH),
    )
    spec = importlib.util.spec_from_loader("seed_regen_test_module", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["seed_regen_test_module"] = module
    loader.exec_module(module)
    return module


seed_regen = _load_seed_regen()


def _configuration_archive(tmp_path: Path) -> Path:
    fmt = export_format_version()
    accounts = _canonical_envelope_bytes("accounts", [{"id": 1, "name": "Cash"}], fmt)
    parties = _canonical_envelope_bytes("parties", [], fmt)
    manifest = [
        {"path": "accounts.json", "sha256": "0" * 64},
        {"path": "parties.json", "sha256": "0" * 64},
    ]
    metadata = {
        "export_type": "configuration",
        "format_version": fmt,
        "schema_version": "001",
        "exported_at": "2026-01-01T00:00:00Z",
        "currency_assumption": "single_currency_numeric_18_2",
        "member_manifest": manifest,
    }
    metadata_bytes = json.dumps(metadata, indent=2).encode("utf-8") + b"\n"
    payloads = {
        "accounts.json": accounts,
        "parties.json": parties,
    }
    archive_bytes = _pack_targz(
        ("accounts.json", "parties.json"),
        payloads,
        metadata_bytes,
    )
    archive = tmp_path / "seed_data.tar.gz"
    archive.write_bytes(archive_bytes)
    return archive


def test_render_deps_mk_lists_manifest_and_metadata() -> None:
    rendered = seed_regen.render_deps_mk(["accounts.json", "parties.json"])
    assert "SEED_MANIFEST_OUTPUTS :=" in rendered
    assert "accounts.json: seed_data.tar.gz" in rendered
    assert "metadata.json: seed_data.tar.gz" in rendered
    assert "do not edit" in rendered.lower()


def test_find_orphan_json_reports_stray_files(tmp_path: Path) -> None:
    (tmp_path / "accounts.json").write_text("{}", encoding="utf-8")
    (tmp_path / "stray.json").write_text("{}", encoding="utf-8")
    orphans = seed_regen.find_orphan_json(tmp_path, ["accounts.json"])
    assert orphans == ["stray.json"]


def test_validate_envelope_rejects_bare_array() -> None:
    fmt = export_format_version()
    raw = json.dumps([{"id": 1}]).encode("utf-8")
    with pytest.raises(seed_regen.SeedRegenError, match="envelope"):
        seed_regen.validate_envelope_member("accounts.json", raw, format_version=fmt)


def test_regen_writes_envelopes_and_deps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    archive = _configuration_archive(data_dir)
    assert archive.name == "seed_data.tar.gz"

    def fake_jq(_jq: str, raw: bytes) -> bytes:
        return raw

    monkeypatch.setattr(seed_regen, "require_jq", lambda: "jq")
    monkeypatch.setattr(seed_regen, "prettify_json", fake_jq)
    monkeypatch.setattr(seed_regen, "run_mkmeta", lambda *_a, **_k: None)

    seed_regen.regen(data_dir=data_dir, repo_root=REPO_ROOT)

    accounts = json.loads((data_dir / "accounts.json").read_text(encoding="utf-8"))
    assert accounts["format_version"] == export_format_version()
    assert accounts["table"] == "accounts"
    assert accounts["rows"] == [{"id": 1, "name": "Cash"}]

    meta = json.loads((data_dir / "metadata.json").read_text(encoding="utf-8"))
    assert meta["export_type"] == "configuration"
    assert [item["path"] for item in meta["member_manifest"]] == [
        "accounts.json",
        "parties.json",
    ]

    deps = (data_dir / "seed_data.deps.mk").read_text(encoding="utf-8")
    assert "parties.json: seed_data.tar.gz" in deps


def test_regen_rejects_complete_export_type(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    fmt = export_format_version()
    metadata = {
        "export_type": "complete",
        "format_version": fmt,
        "member_manifest": [],
    }
    metadata_bytes = json.dumps(metadata).encode("utf-8")
    archive_bytes = _pack_targz((), {}, metadata_bytes)
    (data_dir / "seed_data.tar.gz").write_bytes(archive_bytes)

    monkeypatch.setattr(seed_regen, "require_jq", lambda: "jq")

    with pytest.raises(seed_regen.SeedRegenError, match="configuration"):
        seed_regen.regen(data_dir=data_dir, repo_root=REPO_ROOT)
