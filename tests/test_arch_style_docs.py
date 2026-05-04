"""Guardrails for repo-root architecture and style docs (issue #75)."""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("name", "needles"),
    [
        (
            "ARCH.md",
            [
                "Trust boundaries",
                "format_version",
                "docs/backup-snapshot-format.md",
            ],
        ),
        (
            "STYLE.md",
            [
                "export-dev-seed",
                "sql/dev_seed.sql",
                "Decimal",
                "integration",
            ],
        ),
    ],
)
def test_canonical_docs_exist_and_cover_expected_topics(
    name: str, needles: list[str]
) -> None:
    path = REPO_ROOT / name
    assert path.is_file(), f"missing {path}"
    text = path.read_text(encoding="utf-8")
    for fragment in needles:
        assert fragment in text, f"{name} should mention {fragment!r}"
