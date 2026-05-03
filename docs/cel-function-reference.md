# CEL function reference (import rules)

This document is the **authoritative reference** for **custom functions** available in **CEL** expressions used by the import CEL rule path (`evaluate_cel`, CSV execute with a CEL rule set, `POST /import-rules/cel/evaluate`). It is maintained alongside GitHub issues **[#46](https://github.com/brettski74/TallyBadger/issues/46)** (party-aware functions + party data model), **[#50](https://github.com/brettski74/TallyBadger/issues/50)** (generic attribute helpers), and **[#59](https://github.com/brettski74/TallyBadger/issues/59)** (`debug()` for rule diagnostics).

**Related:** [Import rules engine](import-rules-engine.md) ([#8](https://github.com/brettski74/TallyBadger/issues/8)) — CEL spike contract, `attributes` / `match` activation map, capture gating.

**Convention:** String arguments are trimmed for lookup. For **`party_type`**, **`party_subtype`**, **`revenue_account`**, **`equity_account`**, and **`expense_account`**, a **null** or **blank** argument (after trim) is treated like a non-match and returns **null**—no evaluation error. Other helpers may still error on invalid input where documented. Exact spelling of function names in CEL follows the identifiers registered in code (typically `party`, `party_type`, …).

---

## Status legend

| Status | Meaning |
|--------|---------|
| **#46** | Shipped in [#46](https://github.com/brettski74/TallyBadger/issues/46); keep this doc in sync when behaviour changes. |
| **#50** | Planned in [#50](https://github.com/brettski74/TallyBadger/issues/50); update this doc in the same PR as the implementation. |
| **#59** | Shipped in [#59](https://github.com/brettski74/TallyBadger/issues/59); `debug(x)` and API `debug` arrays. |

---

## `debug(x)` — inspection helper (**#59**)

- **Signature:** `debug(x)` — exactly **one** argument (any CEL value the expression can pass).
- **Return value:** **`x`** unchanged (transparent / identity). The rule outcome must be the same as if `debug` were not present, aside from the side effect below.
- **Side effect:** each call **appends one debug record** while that rule’s CEL program runs (after all regex captures for that rule have succeeded — the same point as `program.evaluate` today). No records are produced when the expression never runs (e.g. capture failure, disabled rule, or evaluation stopped on an earlier rule).
- **Serialization:** Values are converted to **JSON-friendly** snapshots using the same path as attribute round-tripping where possible (`_from_cel_value` in the engine). If a value cannot be represented safely, the engine **falls back** (e.g. string / `repr`). **`debug` must never cause** an import or evaluate request to fail because serialization failed.

### Debug record shape (JSON)

Each record is an object with:

| Field | When present | Meaning |
|-------|----------------|--------|
| **`rule`** | always | Rule label: `rule.name` if set, otherwise `rule[{index}]` (same as trace `_rule_label`). |
| **`value`** | always | JSON-friendly snapshot of the argument after serialization. |
| **`row_number`** | CSV execute only | **1-based** index of the **data** row (same numbering as CSV row validation errors). Omitted on **`POST /import-rules/cel/evaluate`** (no import row). |

### Where `debug` appears in API JSON

The **`debug` key is omitted entirely** when there are **no** records for that response object. When present, **`debug`** is a **JSON array** of records in **call order** within that evaluation.

| API | Location |
|-----|----------|
| **`POST /import-rules/cel/evaluate`** | Optional top-level **`debug`** on the evaluation result. |
| **`POST /imports/csv/execute`** | Optional **`debug`** on **each** `entries[]` item for rows where at least one `debug()` ran. Entries for rows with no `debug()` calls omit the key. |

**Note:** Rows that error or are dropped before a journal entry is built do not appear in `entries[]`; debug captured on paths that never produce an entry is **out of scope for v1** (see #59).

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

### `party_type(str) -> string | null`

- **Argument `str`:** Canonical **party `name`** (not arbitrary haystack).
- **Returns:** Party **role** as a string: `customer`, `vendor`, `both`, or `other` (aligned with `PartyRole` / API).
- **Blank / null argument:** Return **null** (same idea as “no party to describe”).
- **Errors:** Unknown party name or inactive party → evaluation error with a clear message.

### `party_subtype(str) -> string | null`

- **Argument `str`:** Canonical party **name**.
- **Returns:** That party’s **`subtype`** text; when the party has no subtype configured, return an **empty string**.
- **Blank / null argument:** Return **null** (no lookup).
- **Errors:** Unknown or inactive party → evaluation error.

### `revenue_account(str) -> string | null`

- **Argument `str`:** Canonical party **name**.
- **Returns:** **`name`** of the party’s configured **default revenue or equity account** (for posting into account-name fields)—same field as in the UI (“Default revenue / equity account”). Returns **null** when that default is not set (including for parties whose role would not allow setting one at save time—CEL retrieval does not enforce role; see **#61**).
- **Party save:** **`role`** in **`customer`** or **`both`**, account **`type`** **`revenue`** or **`equity`**, etc., are enforced when persisting the party—not when evaluating this function.
- **Blank / null argument:** Return **null**.
- **Errors:** Unknown or inactive party name → evaluation error.

### `equity_account(str) -> string | null`

- **Alias of `revenue_account(str)`** — same argument, same return value, same **null** / error behavior. Lets rules read more naturally (`equity_account("Owner")` vs `revenue_account("Owner")`) when the linked account is equity; either function may return a **revenue** or **equity** account name.

### `expense_account(str) -> string | null`

- **Argument `str`:** Canonical party **name**.
- **Returns:** **`name`** of the party’s configured **default expense account**, or **null** if none is stored (**#61**: no role check on read).
- **Party save:** **`role`** in **`vendor`** or **`both`** and account **`type == expense`** are enforced when persisting—not in CEL.
- **Blank / null argument:** Return **null**.
- **Errors:** Unknown or inactive party name → evaluation error.

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
| *#59 ship* | **`debug(x)`** — identity + ordered debug records; evaluate vs CSV `row_number` and JSON omission rules as above. |

Update this table whenever functions are added or signatures/semantics change.
