"""Unit tests for tar.gz snapshot format 2.0.0 (#251)."""

from __future__ import annotations

import gzip
import io
import json
import tarfile
import zipfile

import pytest

from tallybadger.backup.errors import IncompleteSnapshotError, SnapshotIntegrityError
from tallybadger.backup.snapshot import (
    FORMAT_VERSION_HISTORY,
    _canonical_envelope_bytes,
    _iter_pack_targz,
    _load_targz_members,
    _pack_targz,
    _parse_table_file,
    load_targz_members_from_stream,
    configuration_tables_for_format,
    detect_snapshot_container,
    export_format_version,
    financial_tables_for_format,
    manifest_member_paths,
    snapshot_uses_json_envelopes,
    supported_import_format_versions,
)


def test_export_format_version_is_two_zero_zero() -> None:
    assert export_format_version() == "2.0.0"
    assert FORMAT_VERSION_HISTORY[-1] == "2.0.0"


def test_supported_import_window_after_two_zero_zero() -> None:
    assert supported_import_format_versions() == frozenset({"1.6.0", "1.7.0", "1.8.0", "2.0.0"})


def test_snapshot_uses_json_envelopes_from_two_zero_zero() -> None:
    assert not snapshot_uses_json_envelopes("1.8.0")
    assert snapshot_uses_json_envelopes("2.0.0")


def test_detect_snapshot_container_magic() -> None:
    assert detect_snapshot_container(b"PK\x03\x04" + b"\x00" * 20) == "zip"
    assert detect_snapshot_container(b"\x1f\x8b" + b"\x00" * 20) == "gzip"
    with pytest.raises(IncompleteSnapshotError, match="unrecognized snapshot container"):
        detect_snapshot_container(b"NOTA")


def test_manifest_member_paths_fk_order_not_sorted() -> None:
    payloads = {
        "accounts.json": b"{}",
        "parties.json": b"{}",
        "party_match_patterns.json": b"{}",
        "ledger_settings.json": b"{}",
        "cel_rule_sets.json": b"{}",
        "import_templates.json": b"{}",
        "journal_entry_filter_presets.json": b"{}",
        "cheque_register_filter_presets.json": b"{}",
    }
    paths = manifest_member_paths("configuration", "2.0.0", payloads)
    assert paths[0] == "accounts.json"
    assert paths[-1] == "cheque_register_filter_presets.json"
    assert paths == tuple(payloads.keys())


def test_manifest_attachment_blobs_after_journal_entry_attachments_json() -> None:
    fmt = "2.0.0"
    payloads = {
        f"{table}.json": _canonical_envelope_bytes(table, [], fmt)
        for table in financial_tables_for_format(fmt)
        if table not in ("attachments", "journal_entry_attachments")
    }
    payloads["attachments.json"] = _canonical_envelope_bytes("attachments", [], fmt)
    payloads["journal_entry_attachments.json"] = _canonical_envelope_bytes(
        "journal_entry_attachments",
        [],
        fmt,
    )
    payloads["attachments/1.pdf"] = b"%PDF"
    payloads["attachments/2.png"] = b"\x89PNG"
    paths = manifest_member_paths("financial", fmt, payloads)
    assert paths.index("attachments.json") < paths.index("journal_entry_attachments.json")
    assert paths.index("journal_entry_attachments.json") < paths.index("attachments/1.pdf")
    assert paths[-1] == "attachments/2.png"


def test_iter_pack_targz_yields_multiple_chunks() -> None:
    fmt = "2.0.0"
    payloads = {
        f"parties.json": _canonical_envelope_bytes("parties", [], fmt),
        f"accounts.json": _canonical_envelope_bytes("accounts", [], fmt),
    }
    paths = ("accounts.json", "parties.json")
    meta = b'{"export_type":"configuration","format_version":"2.0.0","member_manifest":[]}'
    chunks = list(_iter_pack_targz(paths, payloads, meta))
    assert len(chunks) > 1
    assert _pack_targz(paths, payloads, meta) == b"".join(chunks)


def test_load_targz_members_from_stream_matches_bytes_loader() -> None:
    fmt = "2.0.0"
    payloads = {
        f"{table}.json": _canonical_envelope_bytes(table, [], fmt)
        for table in configuration_tables_for_format(fmt)
    }
    paths = manifest_member_paths("configuration", fmt, payloads)
    import hashlib

    manifest = [{"path": p, "sha256": hashlib.sha256(payloads[p]).hexdigest()} for p in paths]
    meta_obj = {
        "export_type": "configuration",
        "format_version": "2.0.0",
        "schema_version": "001",
        "member_manifest": manifest,
    }
    meta_bytes = json.dumps(meta_obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    archive = _pack_targz(paths, payloads, meta_bytes)
    from_bytes = _load_targz_members(archive)
    from_stream = load_targz_members_from_stream(io.BytesIO(archive))
    assert from_stream == from_bytes


def test_pack_targz_metadata_last_and_gzip_level_nine() -> None:
    payloads = {"accounts.json": b'{"format_version":"2.0.0","table":"accounts","rows":[]}'}
    paths = ("accounts.json",)
    meta = b'{"export_type":"configuration","format_version":"2.0.0","member_manifest":[]}'
    archive = _pack_targz(paths, payloads, meta)
    assert detect_snapshot_container(archive) == "gzip"
    assert archive[:2] == b"\x1f\x8b"

    with gzip.GzipFile(fileobj=io.BytesIO(archive), mode="rb") as gz:
        with tarfile.open(fileobj=gz, mode="r:") as tar:
            names = [m.name for m in tar.getmembers() if m.isfile()]
    assert names == ["accounts.json", "metadata.json"]


def test_pack_targz_sets_member_mtime() -> None:
    fixed_mtime = 1_735_689_600  # 2025-01-01 00:00:00 UTC
    payloads = {"accounts.json": b"[]"}
    archive = _pack_targz(("accounts.json",), payloads, b"{}", mtime=fixed_mtime)
    with gzip.GzipFile(fileobj=io.BytesIO(archive), mode="rb") as gz:
        with tarfile.open(fileobj=gz, mode="r:") as tar:
            mtimes = {m.name: m.mtime for m in tar.getmembers() if m.isfile()}
    assert mtimes == {"accounts.json": fixed_mtime, "metadata.json": fixed_mtime}


def test_load_targz_members_validates_order_and_hashes() -> None:
    fmt = "2.0.0"
    rows = [{"id": 1, "name": "Cash", "type": "asset", "is_active": True}]
    payloads = {
        f"{table}.json": (
            _canonical_envelope_bytes("accounts", rows, fmt)
            if table == "accounts"
            else _canonical_envelope_bytes(table, [], fmt)
        )
        for table in configuration_tables_for_format(fmt)
    }
    paths = manifest_member_paths("configuration", fmt, payloads)
    import hashlib

    manifest = [{"path": p, "sha256": hashlib.sha256(payloads[p]).hexdigest()} for p in paths]
    meta_obj = {
        "export_type": "configuration",
        "format_version": "2.0.0",
        "schema_version": "001",
        "member_manifest": manifest,
    }
    meta_bytes = json.dumps(meta_obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    archive = _pack_targz(paths, payloads, meta_bytes)
    metadata, files = _load_targz_members(archive)
    assert metadata["format_version"] == "2.0.0"
    parsed = _parse_table_file("accounts.json", files["accounts.json"], format_version="2.0.0")
    assert parsed == rows


def test_load_targz_rejects_metadata_not_last() -> None:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=9) as gz:
        with tarfile.open(fileobj=gz, mode="w") as tar:
            for name, data in (("metadata.json", b"{}"), ("accounts.json", b"[]")):
                info = tarfile.TarInfo(name=name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
    with pytest.raises(IncompleteSnapshotError, match="metadata.json must be the last member"):
        _load_targz_members(buf.getvalue())


def test_load_targz_rejects_manifest_order_mismatch() -> None:
    import hashlib

    payloads = {"accounts.json": b"[]", "parties.json": b"[]"}
    meta = json.dumps(
        {
            "export_type": "configuration",
            "format_version": "2.0.0",
            "member_manifest": [
                {"path": "accounts.json", "sha256": hashlib.sha256(b"[]").hexdigest()},
                {"path": "parties.json", "sha256": hashlib.sha256(b"[]").hexdigest()},
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    # wrong tar order (parties before accounts)
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=9) as gz:
        with tarfile.open(fileobj=gz, mode="w") as tar:
            for path in ("parties.json", "accounts.json"):
                data = payloads[path]
                info = tarfile.TarInfo(name=path)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            info = tarfile.TarInfo(name="metadata.json")
            info.size = len(meta)
            tar.addfile(info, io.BytesIO(meta))
    with pytest.raises(SnapshotIntegrityError, match="tar member order"):
        _load_targz_members(buf.getvalue())


def test_parse_table_file_legacy_bare_array() -> None:
    raw = b'[{"id":1}]'
    assert _parse_table_file("accounts.json", raw, format_version="1.8.0") == [{"id": 1}]


def test_parse_table_file_envelope_table_mismatch() -> None:
    raw = _canonical_envelope_bytes("parties", [], "2.0.0")
    with pytest.raises(IncompleteSnapshotError, match="does not match member name"):
        _parse_table_file("accounts.json", raw, format_version="2.0.0")


def test_load_targz_rejects_extra_member() -> None:
    rows = [{"id": 1, "name": "Cash", "type": "asset", "is_active": True}]
    body = _canonical_envelope_bytes("accounts", rows, "2.0.0")
    payloads = {"accounts.json": body, "surprise.json": b"{}"}
    paths = ("accounts.json",)
    manifest = [{"path": "accounts.json", "sha256": __import__("hashlib").sha256(body).hexdigest()}]
    meta_bytes = json.dumps(
        {
            "export_type": "configuration",
            "format_version": "2.0.0",
            "member_manifest": manifest,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    archive = _pack_targz(paths, {"accounts.json": body}, meta_bytes)
    # inject extra member before metadata by manual repack
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=9) as gz:
        with tarfile.open(fileobj=gz, mode="w") as tar:
            for path, data in (("accounts.json", body), ("surprise.json", b"{}")):
                info = tarfile.TarInfo(name=path)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            info = tarfile.TarInfo(name="metadata.json")
            info.size = len(meta_bytes)
            tar.addfile(info, io.BytesIO(meta_bytes))
    with pytest.raises(SnapshotIntegrityError, match="unexpected tar members"):
        _load_targz_members(buf.getvalue())


def test_legacy_zip_still_detected() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("metadata.json", b"{}")
    assert detect_snapshot_container(buf.getvalue()) == "zip"
