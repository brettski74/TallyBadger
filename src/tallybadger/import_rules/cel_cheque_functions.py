"""CEL extension: cheque register lookup for import rules (#92)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from celpy import celtypes
from celpy.evaluation import CELFunction, Result

from tallybadger.import_rules.cel_stdlib_functions import (
    _cel_int_param,
    _cel_str,
    _parse_iso_calendar_date,
)
from tallybadger.import_rules.errors import ImportRulesCelError
from tallybadger.ledger.models import AccountOut, ChequeOut, PartyOut


def _parse_cheque_entry_date(value: Any) -> date:
    """Journal entry date for `cheque(..., date)`.

    Prefer native ``date`` / ``datetime`` (and CEL timestamp types that behave as such).
    ISO-formatted date or date-time **strings** are accepted via the same rules as
    ``day()`` / ``month()`` / ``match_date()`` — string parsing is for that case only.
    """
    return _parse_iso_calendar_date(value)


def _decimal_for_cheque_import_amount(value: Any) -> Decimal:
    """Normalize the import-side amount (CSV-derived; authoritative vs register)."""
    if value is None:
        raise ImportRulesCelError("cheque: amount is null")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, celtypes.IntType):
        return Decimal(int(value))
    if isinstance(value, celtypes.UintType):
        return Decimal(int(value))
    if isinstance(value, celtypes.DoubleType):
        return Decimal(str(float(value)))
    if isinstance(value, celtypes.StringType):
        s = str(value).strip().replace(",", "")
        if not s:
            raise ImportRulesCelError("cheque: amount is blank")
        try:
            return Decimal(s)
        except InvalidOperation as exc:
            raise ImportRulesCelError(f"cheque: invalid amount {value!r}") from exc
    if isinstance(value, bool):
        raise ImportRulesCelError("cheque: amount cannot be a boolean")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        s = value.strip().replace(",", "")
        if not s:
            raise ImportRulesCelError("cheque: amount is blank")
        try:
            return Decimal(s)
        except InvalidOperation as exc:
            raise ImportRulesCelError(f"cheque: invalid amount {value!r}") from exc
    raise ImportRulesCelError(f"cheque: unsupported amount type {type(value).__name__}")


def _cheque_import_amount_matches_register(import_amt: Decimal, register_amt: Decimal) -> bool:
    """True when magnitudes match.

    Bank CSV lines often show a cheque as a **negative** credit to chequing; the register
    stores the cheque face amount as a **positive** ``Decimal``. Only magnitude is compared
    for the mismatch review (see #92).
    """
    return abs(import_amt) == abs(register_amt)


def _format_cheque_review_dollars(amount: Decimal) -> str:
    """Format for amount-mismatch review text: USD ``$``, comma thousands, two fraction digits."""
    q = amount.quantize(Decimal("0.01"))
    if q < 0:
        return f"-${abs(q):,.2f}"
    return f"${q:,.2f}"


def _cel_map_from_python(d: dict[str, Any]) -> celtypes.MapType:
    entries: dict[Any, Any] = {}
    for k, v in d.items():
        ck = celtypes.StringType(str(k))
        if isinstance(v, str):
            entries[ck] = celtypes.StringType(v)
        elif isinstance(v, Decimal):
            entries[ck] = celtypes.DoubleType(float(v))
        elif isinstance(v, float):
            entries[ck] = celtypes.DoubleType(v)
        elif isinstance(v, int):
            entries[ck] = celtypes.IntType(v)
        elif isinstance(v, list):
            entries[ck] = celtypes.ListType([celtypes.StringType(str(item)) for item in v])
        else:
            raise TypeError(f"cheque map: unsupported value for {k!r}: {type(v).__name__}")
    return celtypes.MapType(entries)


def build_cheque_cel_functions(
    cheques: list[ChequeOut] | None,
    accounts: list[AccountOut] | None,
    parties: list[PartyOut] | None,
) -> dict[str, CELFunction]:
    """Register ``cheque(account, nr, amt, date)`` for import CEL (open cheques only)."""
    acct_rows = accounts or []
    accounts_by_id = {a.id: a for a in acct_rows}
    by_trimmed_name: dict[str, AccountOut] = {}
    for a in acct_rows:
        by_trimmed_name[a.name.strip()] = a

    party_name_by_id = {p.id: p.name for p in (parties or [])}

    by_credit_name_and_number: dict[tuple[str, int], ChequeOut] = {}
    for ch in cheques or []:
        if ch.status != "open":
            continue
        cr = accounts_by_id.get(ch.credit_account_id)
        if cr is None:
            continue
        by_credit_name_and_number[(cr.name.strip(), ch.cheque_number)] = ch

    def cheque_fn(account: Any, nr: Any, amt: Any, date_arg: Any) -> Result:
        account_key = _cel_str(account)
        nr_int = _cel_int_param(nr, label="cheque: cheque number", min_value=1)
        import_amt = _decimal_for_cheque_import_amount(amt)
        entry_date = _parse_cheque_entry_date(date_arg)

        def no_match_message(msg: str) -> celtypes.MapType:
            return _cel_map_from_python({"review-messages": [msg]})

        if not account_key:
            return no_match_message("cheque: credit account name is blank; cannot match an open cheque.")

        credit_acc = by_trimmed_name.get(account_key)
        if credit_acc is None or not credit_acc.is_active:
            disp = account_key
            return no_match_message(
                f"No open cheque found: credit account {disp!r} is unknown or inactive for cheque number {nr_int}.",
            )

        ch = by_credit_name_and_number.get((account_key, nr_int))
        if ch is None:
            return no_match_message(
                f"No open cheque found for account {credit_acc.name!r} and cheque number {nr_int}.",
            )

        dr_acc = accounts_by_id.get(ch.debit_account_id)
        dr_name = dr_acc.name if dr_acc else f"#{ch.debit_account_id}"

        # Register amount is exposed as `cheque-amount`, not `amount`, so CSV / rule-derived
        # posting amount stays authoritative. Use a CEL double (same idea as bag Decimals in
        # activation) so `+` and comparisons behave numerically, not as string concat.
        out: dict[str, Any] = {
            "dr-account": dr_name,
            "cheque-id": ch.id,
            "summary": ch.summary,
            "cheque-amount": ch.amount,
        }
        if ch.party_id is not None:
            pname = party_name_by_id.get(ch.party_id)
            if pname is not None:
                out["dr-party"] = pname

        messages: list[str] = []
        if not _cheque_import_amount_matches_register(import_amt, ch.amount):
            imp_s = _format_cheque_review_dollars(import_amt)
            reg_s = _format_cheque_review_dollars(ch.amount)
            messages.append(
                f"Import amount {imp_s} differs from register amount {reg_s} for cheque "
                f"number {nr_int} on account {credit_acc.name!r}.",
            )
        if entry_date < ch.issue_date:
            messages.append(
                f"Journal entry date {entry_date.isoformat()} is before cheque issue date "
                f"{ch.issue_date.isoformat()} (cheque #{nr_int}, account {credit_acc.name!r}).",
            )
        if messages:
            out["review-messages"] = messages

        return _cel_map_from_python(out)

    return {"cheque": cheque_fn}
