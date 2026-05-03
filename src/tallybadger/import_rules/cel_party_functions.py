"""CEL extension functions backed by ledger party snapshots (#46)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from celpy import celtypes
from celpy.evaluation import CELFunction, Result

from tallybadger.import_rules.errors import ImportRulesCelError
from tallybadger.ledger.models import PartyOut


def _cel_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, celtypes.StringType):
        return str(value).strip()
    return str(value).strip()


@dataclass(frozen=True)
class CelPartySnapshot:
    """Immutable party row for CEL lookups (active parties only at call site)."""

    id: int
    name: str
    role: str
    subtype: str | None
    is_active: bool
    patterns: tuple[str, ...]
    default_revenue_account_name: str | None
    default_expense_account_name: str | None


def party_snapshots_from_outs(parties: list[PartyOut]) -> list[CelPartySnapshot]:
    return [
        CelPartySnapshot(
            id=p.id,
            name=p.name,
            role=p.role,
            subtype=p.subtype,
            is_active=p.is_active,
            patterns=tuple(p.match_patterns),
            default_revenue_account_name=p.default_revenue_account_name,
            default_expense_account_name=p.default_expense_account_name,
        )
        for p in parties
    ]


def build_party_cel_functions(parties: list[PartyOut]) -> dict[str, CELFunction]:
    """Return cel-python function bindings for import CEL rules."""
    snaps = party_snapshots_from_outs(parties)
    active = [s for s in snaps if s.is_active]
    active_sorted = sorted(active, key=lambda s: s.id)
    by_name = {s.name: s for s in snaps if s.is_active}

    compiled: list[tuple[CelPartySnapshot, list[re.Pattern[str]]]] = []
    for s in active_sorted:
        row: list[re.Pattern[str]] = []
        for pat in s.patterns:
            try:
                row.append(re.compile(pat))
            except re.error as exc:
                raise ImportRulesCelError(f"invalid stored regex for party {s.name!r}: {exc}") from exc
        compiled.append((s, row))

    def party(hay: Any) -> Result:
        text = _cel_str(hay)
        if not text:
            return None
        matched: list[str] = []
        for snap, patterns in compiled:
            if not patterns:
                continue
            for cre in patterns:
                if cre.search(text):
                    matched.append(snap.name)
                    break
        uniq: list[str] = list(dict.fromkeys(matched))
        if len(uniq) > 1:
            raise ImportRulesCelError(
                "multiple parties matched the same text: " + ", ".join(sorted(uniq)),
            )
        if not uniq:
            return None
        return celtypes.StringType(uniq[0])

    def party_type(name: Any) -> Result:
        key = _cel_str(name)
        if not key:
            raise ImportRulesCelError("party_type() requires a non-blank party name")
        snap = by_name.get(key)
        if snap is None:
            raise ImportRulesCelError(f"unknown active party {key!r}")
        return celtypes.StringType(snap.role)

    def party_subtype(name: Any) -> Result:
        key = _cel_str(name)
        if not key:
            raise ImportRulesCelError("party_subtype() requires a non-blank party name")
        snap = by_name.get(key)
        if snap is None:
            raise ImportRulesCelError(f"unknown active party {key!r}")
        st = snap.subtype or ""
        return celtypes.StringType(st)

    def revenue_account(name: Any) -> Result:
        key = _cel_str(name)
        if not key:
            raise ImportRulesCelError("revenue_account() requires a non-blank party name")
        snap = by_name.get(key)
        if snap is None:
            raise ImportRulesCelError(f"unknown active party {key!r}")
        if snap.role not in ("customer", "both"):
            raise ImportRulesCelError(
                f"party {key!r} has role {snap.role!r}; default revenue/equity account applies only to customer or both",
            )
        acc = snap.default_revenue_account_name
        if not acc:
            raise ImportRulesCelError(
                f"party {key!r} has no default revenue or equity account configured",
            )
        return celtypes.StringType(acc)

    def expense_account(name: Any) -> Result:
        key = _cel_str(name)
        if not key:
            raise ImportRulesCelError("expense_account() requires a non-blank party name")
        snap = by_name.get(key)
        if snap is None:
            raise ImportRulesCelError(f"unknown active party {key!r}")
        if snap.role not in ("vendor", "both"):
            raise ImportRulesCelError(
                f"party {key!r} has role {snap.role!r}; default expense account applies only to vendor or both",
            )
        acc = snap.default_expense_account_name
        if not acc:
            raise ImportRulesCelError(f"party {key!r} has no default expense account configured")
        return celtypes.StringType(acc)

    return {
        "party": party,
        "party_type": party_type,
        "party_subtype": party_subtype,
        "revenue_account": revenue_account,
        "expense_account": expense_account,
    }
