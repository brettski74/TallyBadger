# CEL function reference (import rules)

This document is the **authoritative reference** for **custom functions** available in **CEL** expressions used by the import CEL rule path (`evaluate_cel`, CSV execute with a CEL rule set, `POST /import-rules/cel/evaluate`). It is maintained alongside GitHub issues **[#46](https://github.com/brettski74/TallyBadger/issues/46)** (party-aware functions + party data model) and **[#50](https://github.com/brettski74/TallyBadger/issues/50)** (generic attribute helpers).

**Related:** [Import rules engine](import-rules-engine.md) ([#8](https://github.com/brettski74/TallyBadger/issues/8)) — CEL spike contract, `attributes` / `match` activation map, capture gating.

**Convention:** Unless stated otherwise, string arguments are trimmed for lookup; empty strings after trim are invalid input and should surface a **CEL evaluation error** (same class as today: `ImportRulesCelError` → 422 on import). Exact spelling of function names in CEL follows the identifiers registered in code (typically `party`, `party_type`, …).

---

## Status legend

| Status | Meaning |
|--------|---------|
| **#46** | Shipped in [#46](https://github.com/brettski74/TallyBadger/issues/46); keep this doc in sync when behaviour changes. |
| **#50** | Planned in [#50](https://github.com/brettski74/TallyBadger/issues/50); update this doc in the same PR as the implementation. |

---

## Party and account helpers (**#46**)

These functions read **current ledger state** (active parties, accounts) passed into the CEL runtime when rules run (e.g. CSV import execute). They do **not** change import posting rules: journal construction still requires **exact** `parties.name` (and account names) in the bag where the pipeline already enforces that.

### `party(str) -> string | null`

- **Argument `str`:** Haystack text (e.g. raw bank description or concatenated fields) to match against each party’s **ordered regex patterns**.
- **Matching:** For each **active** party, consider patterns in **`sort_order`** ascending. Use Python **`re.search(pattern, haystack)`** per pattern (same engine as elsewhere; document default flags—typically none, so authors may use `(?i)` for case-insensitivity).
- **Success:** Return the party’s canonical **`name`** (the string import posting expects).
- **Ambiguity:** If **more than one** active party has at least one pattern that matches the haystack, **fail** the CEL evaluation with an error that **lists the matched party names** (and optionally ids in the message for support).
- **No match:** If no active party’s patterns match, return **null** (e.g. branch with `party(x) != null ? … : …`).

*Note:* Parties with **no** patterns never contribute to `party(str)`; exact-name resolution for posting is unchanged and separate.

### `party_type(str) -> string`

- **Argument `str`:** Canonical **party `name`** (not arbitrary haystack).
- **Returns:** Party **role** as a string: `customer`, `vendor`, `both`, or `other` (aligned with `PartyRole` / API).
- **Errors:** Unknown party name, inactive party, or blank input → evaluation error with a clear message.

### `party_subtype(str) -> string`

- **Argument `str`:** Canonical party **name**.
- **Returns:** That party’s **`subtype`** text; when unset, return an **empty string** (document if implementation chooses CEL `null` instead—keep this file in sync).
- **Errors:** Unknown or inactive party → evaluation error.

### `revenue_account(str) -> string`

- **Argument `str`:** Canonical party **name**.
- **Returns:** **`name`** of the party’s configured **default revenue or equity account** (for posting into account-name fields)—same field as in the UI (“Default revenue / equity account”).
- **Eligibility:** Party **`role`** must be **`customer`** or **`both`**. The party must have **`default_revenue_account_id`** set to an **active** account with **`type`** **`revenue`** or **`equity`** (validated at party save).
- **Errors:** Wrong role, missing default, inactive party, unknown name, inactive account, or wrong account type → evaluation error with explicit reason.

### `equity_account(str) -> string`

- **Alias of `revenue_account(str)`** — same argument, same return value, same validation. Lets rules read more naturally (`equity_account("Owner")` vs `revenue_account("Owner")`) when the linked account is equity; either function may return a **revenue** or **equity** account name.

### `expense_account(str) -> string`

- **Argument `str`:** Canonical party **name**.
- **Returns:** **`name`** of the party’s configured **default expense account**.
- **Eligibility:** Party **`role`** must be **`vendor`** or **`both`**. Validate at party save: account `type == expense`.
- **Errors:** Same style as `revenue_account`.

---

## Generic helpers (**#50**)

### `abs(v) -> number`

- **Argument `v`:** Numeric value (`int` / `double` in CEL terms).
- **Returns:** Absolute value in the same numeric kind as far as CEL/cel-python allows; document any coercion from Decimal in the attribute bag.

### `day(d) -> int`

- **Argument `d`:** Date or date-time (CEL string ISO date/datetime from attributes, or a type the runtime maps).
- **Returns:** Day of month **1–31** in the interpreted calendar date.

### `month(d) -> int`

- **Argument `d`:** Date or date-time.
- **Returns:** Month **1–12**.

### `account_type(str) -> string`

- **Argument `str`:** Canonical **account `name`**.
- **Returns:** Account type string: `asset`, `liability`, `equity`, `revenue`, `expense`, or `suspense` (aligned with ledger models).
- **Errors:** Unknown or inactive account → evaluation error.

### `match_date(d, n, t) -> bool`

- **Arguments:** `d` — date (or date-time; use the **calendar date** in the evaluation timezone documented for #50); `n` — target day-of-month (**1–31**); `t` — non-negative integer **tolerance** (days).
- **Returns:** Let `dom` be the day-of-month of `d`, and `dim` the number of days in that month. Let `low = max(1, n - t)` and `high = min(dim, n + t)`. Returns **`true`** iff **`low <= dom <= high`** (inclusive). This matches calendar-month-local “near day *n*” without wrapping to adjacent months.
- **Examples:** For **2026-04-10**, `match_date(d, 8, 2)` → **true** (`dom` 10 ∈ [6, 10]); `match_date(d, 8, 1)` → **false** (10 ∉ [7, 9]).

---

## Changelog (maintenance)

| When | Change |
|------|--------|
| *(initial)* | Stub reference: #46 party helpers + #50 generic helpers split from monolithic #50 description. |
| *#46 ship* | `party()` returns **null** when no pattern matches; errors only on **multiple** matches. Party model, API, UI, and CEL wiring documented here. |
| *#46 follow-up* | **`equity_account(str)`** added as an alias of **`revenue_account(str)`** (same field and return value). |

Update this table whenever functions are added or signatures/semantics change.
