"""Scan attachment filename pattern: {yyyymmdd}.{party-kebab}.{summary-kebab}.jpg."""

import re
from datetime import date


def to_kebab_segment(text: str) -> str:
    lowered = text.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "unknown"


def build_scan_filename(*, entry_date: date, party_name: str, summary: str) -> str:
    date_part = entry_date.strftime("%Y%m%d")
    party_part = to_kebab_segment(party_name)
    summary_part = to_kebab_segment(summary)
    return f"{date_part}.{party_part}.{summary_part}.jpg"
