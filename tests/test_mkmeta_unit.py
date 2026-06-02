"""Unit tests for standalone scripts/mkmeta (#216)."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MKMETA_PATH = REPO_ROOT / "scripts" / "mkmeta"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "mkmeta"


def _load_mkmeta():
    loader = importlib.machinery.SourceFileLoader("mkmeta_test_module", str(MKMETA_PATH))
    spec = importlib.util.spec_from_loader("mkmeta_test_module", loader)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["mkmeta_test_module"] = module
    spec.loader.exec_module(module)
    return module


mkmeta = _load_mkmeta()


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def test_mkmeta_load_metadata_accepts_missing_or_invalid_sha256() -> None:
    data = mkmeta.load_metadata(FIXTURE / "metadata.json")
    assert len(data["member_manifest"]) == 2
    assert data["member_manifest"][1].get("sha256") is None


def test_mkmeta_compute_manifest_digests_matches_files() -> None:
    metadata = mkmeta.load_metadata(FIXTURE / "metadata.json")
    digests = mkmeta.compute_manifest_digests(metadata, base_dir=FIXTURE)
    assert digests["accounts.json"] == _sha256_file(FIXTURE / "accounts.json")
    assert digests["attachments/blob.bin"] == _sha256_file(FIXTURE / "attachments" / "blob.bin")


def test_mkmeta_apply_digests_writes_lowercase_hex() -> None:
    metadata = mkmeta.load_metadata(FIXTURE / "metadata.json")
    digests = mkmeta.compute_manifest_digests(metadata, base_dir=FIXTURE)
    mkmeta.apply_digests_to_metadata(metadata, digests)
    for item in metadata["member_manifest"]:
        value = item["sha256"]
        assert len(value) == 64
        assert value == value.lower()


def test_mkmeta_find_check_mismatches_reports_stale_and_missing(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_text("[]", encoding="utf-8")
    (tmp_path / "b.json").write_text("[]", encoding="utf-8")
    metadata = {
        "member_manifest": [
            {"path": "a.json", "sha256": "wrong"},
            {"path": "b.json"},
        ]
    }
    mismatches = mkmeta.find_check_mismatches(metadata, base_dir=tmp_path)
    assert set(mismatches) == {"a.json", "b.json"}


def test_mkmeta_find_check_mismatches_passes_when_correct(tmp_path: Path) -> None:
    path = tmp_path / "only.json"
    path.write_text("{}", encoding="utf-8")
    digest = _sha256_file(path)
    metadata = {"member_manifest": [{"path": "only.json", "sha256": digest}]}
    assert mkmeta.find_check_mismatches(metadata, base_dir=tmp_path) == []


def test_mkmeta_main_resolves_members_relative_to_metadata_file_dir(tmp_path: Path) -> None:
    meta_dir = tmp_path / "sub"
    meta_dir.mkdir()
    member = meta_dir / "table.json"
    member.write_text("[]", encoding="utf-8")
    meta = meta_dir / "metadata.json"
    meta.write_text(json.dumps({"member_manifest": [{"path": "table.json"}]}), encoding="utf-8")

    original_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        mkmeta.main(["-i", "sub/metadata.json", "--quiet"])
    finally:
        os.chdir(original_cwd)

    updated = json.loads(meta.read_text(encoding="utf-8"))
    assert updated["member_manifest"][0]["sha256"] == _sha256_file(member)


def test_mkmeta_resolve_member_rejects_escape(tmp_path: Path) -> None:
    base = tmp_path / "base"
    base.mkdir()
    with pytest.raises(mkmeta.MkmetaError, match="outside metadata directory"):
        mkmeta.resolve_member_file(base_dir=base, manifest_path="../outside.json")


def test_mkmeta_assert_hashable_member_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "real.json"
    target.write_text("[]", encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(mkmeta.MkmetaError, match="symlink"):
        mkmeta.assert_hashable_member(link, manifest_path="link.json")


def test_mkmeta_assert_hashable_member_rejects_missing(tmp_path: Path) -> None:
    missing = tmp_path / "nope.json"
    with pytest.raises(mkmeta.MkmetaError, match="missing"):
        mkmeta.assert_hashable_member(missing, manifest_path="nope.json")


def test_mkmeta_write_metadata_creates_backup_with_local_timestamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixed = datetime(2026, 5, 27, 14, 30, 45)
    monkeypatch.setattr(mkmeta, "backup_timestamp_label", lambda: fixed.strftime("%Y%m%d-%H%M%S"))

    output = tmp_path / "metadata.json"
    output.write_text('{"member_manifest":[]}', encoding="utf-8")
    metadata = {"member_manifest": []}

    mkmeta.write_metadata_file(metadata, output, retain=None, quiet=True)

    backup = tmp_path / "metadata.json.20260527-143045"
    assert backup.is_file()
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written == metadata


def test_mkmeta_prune_backups_keeps_newest_by_filename_timestamp(tmp_path: Path) -> None:
    names = [
        "metadata.json.20260101-000000",
        "metadata.json.20260102-000000",
        "metadata.json.20260103-000000",
        "metadata.json.20260104-000000",
    ]
    for name in names:
        (tmp_path / name).write_text("old", encoding="utf-8")

    removed = mkmeta.prune_backups(directory=tmp_path, base_name="metadata.json", retain=2)
    assert [path.name for path in removed] == names[:2]
    remaining = sorted(path.name for path in tmp_path.iterdir() if path.is_file())
    assert remaining == names[2:]


def test_mkmeta_main_write_skips_when_digests_already_current(tmp_path: Path) -> None:
    work = tmp_path / "snap"
    work.mkdir()
    for rel in ("accounts.json", "attachments/blob.bin", "metadata.json"):
        src = FIXTURE / rel
        dest = work / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())

    meta_path = work / "metadata.json"
    mkmeta.main(["-i", str(meta_path), "-o", str(meta_path), "--quiet"])
    before_mtime = meta_path.stat().st_mtime
    backups_before = list(work.glob("metadata.json.*"))

    mkmeta.main(["-i", str(meta_path), "-o", str(meta_path), "--quiet"])

    assert meta_path.stat().st_mtime == before_mtime
    assert list(work.glob("metadata.json.*")) == backups_before


def test_mkmeta_main_write_updates_fixture(tmp_path: Path) -> None:
    work = tmp_path / "snap"
    work.mkdir()
    for rel in ("accounts.json", "attachments/blob.bin", "metadata.json"):
        src = FIXTURE / rel
        dest = work / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())

    meta_path = work / "metadata.json"
    mkmeta.main(["-i", str(meta_path), "-o", str(meta_path), "--quiet"])

    updated = json.loads(meta_path.read_text(encoding="utf-8"))
    assert updated["export_type"] == "complete"
    paths = {item["path"]: item["sha256"] for item in updated["member_manifest"]}
    assert paths["accounts.json"] == _sha256_file(work / "accounts.json")
    assert paths["attachments/blob.bin"] == _sha256_file(work / "attachments" / "blob.bin")


def test_mkmeta_main_check_exits_nonzero_on_mismatch(tmp_path: Path) -> None:
    meta = tmp_path / "metadata.json"
    data_file = tmp_path / "one.json"
    data_file.write_text("x", encoding="utf-8")
    meta.write_text(
        json.dumps({"member_manifest": [{"path": "one.json", "sha256": "bad"}]}),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit) as exc:
        mkmeta.main(["-i", str(meta), "--check"])
    assert exc.value.code == 1


def test_mkmeta_main_check_passes_when_digests_match(tmp_path: Path) -> None:
    data_file = tmp_path / "one.json"
    data_file.write_text("x", encoding="utf-8")
    digest = _sha256_file(data_file)
    meta = tmp_path / "metadata.json"
    meta.write_text(
        json.dumps({"member_manifest": [{"path": "one.json", "sha256": digest}]}),
        encoding="utf-8",
    )
    mkmeta.main(["-i", str(meta), "--check", "--quiet"])


def test_mkmeta_main_retain_flag_prunes_old_backups(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mkmeta, "backup_timestamp_label", lambda: "20260105-120000")

    for stamp in ("20251228-000000", "20251229-000000", "20251230-000000", "20251231-000000"):
        (tmp_path / f"metadata.json.{stamp}").write_text("old", encoding="utf-8")

    data_file = tmp_path / "t.json"
    data_file.write_text("[]", encoding="utf-8")
    output = tmp_path / "metadata.json"
    output.write_text(json.dumps({"member_manifest": [{"path": "t.json"}]}), encoding="utf-8")

    mkmeta.main(["-i", str(output), "-r", "--quiet"])

    backups = sorted(
        path.name
        for path in tmp_path.iterdir()
        if path.is_file() and path.name.startswith("metadata.json.")
    )
    assert backups == [
        "metadata.json.20251230-000000",
        "metadata.json.20251231-000000",
        "metadata.json.20260105-120000",
    ]


def test_mkmeta_parse_args_r_shorthand() -> None:
    args = mkmeta.parse_args(["-r"])
    assert args.r is True


def test_mkmeta_resolve_retain_count() -> None:
    assert mkmeta.resolve_retain_count(mkmeta.parse_args(["-r"])) == 3
    assert mkmeta.resolve_retain_count(mkmeta.parse_args(["--retain", "5"])) == 5
    assert mkmeta.resolve_retain_count(mkmeta.parse_args([])) is None


def test_mkmeta_should_write_output_change_only() -> None:
    same = Path("/tmp/meta.json")
    other = Path("/tmp/out.json")
    assert mkmeta.should_write_output(
        input_path=same,
        output_path=same,
        mismatches=[],
        change_only=True,
    ) is False
    assert mkmeta.should_write_output(
        input_path=same,
        output_path=same,
        mismatches=["a.json"],
        change_only=True,
    ) is True
    assert mkmeta.should_write_output(
        input_path=same,
        output_path=other,
        mismatches=[],
        change_only=True,
    ) is True


def test_mkmeta_main_change_writes_when_output_differs_and_digests_current(
    tmp_path: Path,
) -> None:
    work = tmp_path / "snap"
    work.mkdir()
    for rel in ("accounts.json", "attachments/blob.bin", "metadata.json"):
        src = FIXTURE / rel
        dest = work / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())

    meta_path = work / "metadata.json"
    mkmeta.main(["-i", str(meta_path), "-o", str(meta_path), "--quiet"])

    out_path = work / "metadata-copy.json"
    mkmeta.main(["-i", str(meta_path), "-o", str(out_path), "-c", "--quiet"])
    assert out_path.is_file()
    assert json.loads(out_path.read_text(encoding="utf-8")) == json.loads(
        meta_path.read_text(encoding="utf-8")
    )


def test_mkmeta_main_change_skips_when_same_file_and_digests_current(tmp_path: Path) -> None:
    work = tmp_path / "snap"
    work.mkdir()
    for rel in ("accounts.json", "attachments/blob.bin", "metadata.json"):
        src = FIXTURE / rel
        dest = work / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())

    meta_path = work / "metadata.json"
    mkmeta.main(["-i", str(meta_path), "-o", str(meta_path), "--quiet"])
    before_mtime = meta_path.stat().st_mtime
    backups_before = list(work.glob("metadata.json.*"))

    mkmeta.main(["-i", str(meta_path), "-o", str(meta_path), "-c", "--quiet"])

    assert meta_path.stat().st_mtime == before_mtime
    assert list(work.glob("metadata.json.*")) == backups_before


def test_mkmeta_parse_args_c_shorthand() -> None:
    args = mkmeta.parse_args(["-c"])
    assert args.change is True
