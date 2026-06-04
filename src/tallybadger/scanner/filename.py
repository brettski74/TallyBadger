"""Scan attachment filename patterns."""

import re
from datetime import date


def to_kebab_segment(text: str) -> str:
    lowered = text.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "unknown"


def build_journal_entry_scan_filename(
    *,
    entry_date: date,
    summary: str,
    party_name: str | None = None,
) -> str:
    """Filename for scan-and-attach on an existing journal entry.

    Omits the party segment when ``party_name`` is None (no party on the JE).
    """
    date_part = entry_date.strftime("%Y%m%d")
    summary_part = to_kebab_segment(summary)
    if party_name is None:
        return f"{date_part}.{summary_part}.jpg"
    party_part = to_kebab_segment(party_name)
    return f"{date_part}.{party_part}.{summary_part}.jpg"


def build_accrual_scan_filename(*, entry_date: date, party_name: str, summary: str) -> str:
    """Filename for scan-to-accrual (US-2); includes party segment."""
    date_part = entry_date.strftime("%Y%m%d")
    party_part = to_kebab_segment(party_name)
    summary_part = to_kebab_segment(summary)
    return f"{date_part}.{party_part}.{summary_part}.jpg"


def build_accrual_scan_plan_name(*, entry_date: date, party_name: str, summary: str) -> str:
    """Default one-off accrual plan name aligned with scan filename segments (#259)."""
    date_part = entry_date.strftime("%Y%m%d")
    party_part = party_name.strip()
    summary_part = summary.strip()
    return f"{date_part} {party_part} {summary_part}"
