# CEL function reference (import rules)

This document is the **authoritative reference** for **custom functions** available in **CEL** expressions used by the import CEL rule path (`evaluate_cel`, CSV execute with a CEL rule set, `POST /import-rules/cel/evaluate`). It is maintained alongside GitHub issues **[#46](https://github.com/brettski74/TallyBadger/issues/46)** (party-aware functions + party data model), **[#50](https://github.com/brettski74/TallyBadger/issues/50)** (generic attribute helpers), **[#57](https://github.com/brettski74/TallyBadger/issues/57)** (`unset()` for removing keys from the `set` map / attribute bag), **[#59](https://github.com/brettski74/TallyBadger/issues/59)** (`debug()` for rule diagnostics), and **[#92](https://github.com/brettski74/TallyBadger/issues/92)** (`cheque()` register lookup).

**Related:** [Import rules engine](import-rules-engine.md) ([#8](https://github.com/brettski74/TallyBadger/issues/8)) — CEL spike contract, `attributes` / `match` activation map, capture gating.

**Convention:** String arguments are trimmed for lookup. For **`party_type`**, **`party_subtype`**, **`revenue_account`**, **`equity_account`**, and **`expense_account`**, a **null** or **blank** argument (after trim) is treated like a non-match and returns **null**—no evaluation error. Other helpers may still error on invalid input where documented. Exact spelling of function names in CEL follows the identifiers registered in code (typically `party`, `party_type`, …).

---

## Status legend

| Status | Meaning |
|--------|---------|
| **#46** | Shipped in [#46](https://github.com/brettski74/TallyBadger/issues/46); keep this doc in sync when behaviour changes. |
| **#50** | Shipped in [#50](https://github.com/brettski74/TallyBadger/issues/50); generic helpers below—keep this doc in sync when behaviour changes. |
| **#57** | Shipped in [#57](https://github.com/brettski74/TallyBadger/issues/57); `unset()` and `set` map removal semantics. |
| **#59** | Shipped in [#59](https://github.com/brettski74/TallyBadger/issues/59); `debug(x)` and API `debug` arrays. |
| **#92** | Shipped in [#92](https://github.com/brettski74/TallyBadger/issues/92); `cheque()` open-register lookup and CSV `cheque-id` wiring. |

---

## `unset()` — remove a key from the attribute bag (**#57**)

- **Signature:** **`unset()`** — **zero** arguments.
- **Return value:** An **engine-only marker** (not a user-facing string). Use it **only** as a value inside the **`set`** map of a matched rule payload.
- **Semantics:** For an entry **`"someKey": unset()`** in **`set`**, the engine **removes** **`someKey`** from the row attribute bag if present; if the key was absent, **no-op**. The trace records **`remove_attribute`** with **`rule`** and **`name`** (see [import rules engine](import-rules-engine.md) — trace events).
- **`null` does not remove keys:** **`{"set": {"x": null}}`** still assigns Python **`None`** and leaves **`x`** in the bag. Only **`unset()`** removes the key.

### Example

```cel
{"set": {"scratch": unset()}}
```

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
| **`POST /imports/csv/execute`** (HTTP **422**) | Each **`detail.row_errors[]`** item may include the same optional **`debug`** array when CEL ran for that row before validation failed building the journal entry (**#57**). Omitted when empty or when CEL did not run (e.g. cell parse errors only). |

**Note:** Rows that are **dropped** by CEL still do not appear in `entries[]`; **`debug` on 422 `row_errors`** covers rows that failed after CEL produced a bag (same records that would have been on a successful `entries[]` row for that line).

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

## `cheque(account, nr, amt, date)` — open cheque register lookup (**#92**)

- **Signature:** **`cheque(account, nr, amt, date)`** — four arguments.
- **Data source:** **`evaluate_cel`** and CSV execute pass **`list_cheques`** with **`status=open`** only (same snapshot for the whole evaluation). Inactive credit accounts are not used for matching.
- **Return value:** Always a **CEL map** (never **`null`**). Use it as the whole **`set`** value, e.g. **`{"set": cheque(...)}`**, so keys merge into the row attribute bag like any other **`set`** map.

### Arguments

| Arg | Meaning |
|-----|--------|
| **`account`** | **Credit account** **`name`** (trimmed), matching the cheque register’s **credit** side (the “cheque” / bank account). Must be **active** and present in the account snapshot for a successful match. |
| **`nr`** | **Cheque number** — positive integer as **`int`**, whole **`double`**, or **numeric string** (e.g. regex capture); strings are coerced so rules stay short. |
| **`amt`** | **Import-side amount** — the value from the CSV row (or derived from it). This is treated as the **authoritative** amount for posting: the function **never** returns **`amount`**, so nothing overwrites that. **`amt`** is used only to **compare** against the register and to emit **review** text when it differs. On a match, the register figure is exposed separately as **`cheque-amount`** (string, decimal form) for later rules if needed. |
| **`date`** | **Journal entry date** for the row. **Preferred:** a real **`date`** / **`datetime`** (or CEL timestamp) after attribute activation — same as other date fields. **Also accepted:** non-blank **ISO** **date** (`YYYY-MM-DD`) or **date-time** strings, using the same rules as **`day`** / **`month`** / **`match_date`** (string parsing is for that case). |

### On match (open cheque found for credit account + number)

The map includes at least:

- **`dr-account`** — debit account **`name`** from the register row.
- **`cheque-id`** — integer id (also read by CSV import when building **`journal_entries.cheque_id`**).
- **`summary`** — register **`summary`** for the cheque.
- **`cheque-amount`** — register **amount** as a **string** (e.g. `100.00`). This is **not** named **`amount`** so the CSV / rule **`amount`** used for posting stays the source of truth; authors can still read **`attr["cheque-amount"]`** (or **`attributes[...]`**) in later rules for comparisons or messaging.

**`dr-party`:** included **only** when the register row has a **`party_id`** and that id resolves to a **party name** in the party snapshot. If there is no party on the cheque, **omit** **`dr-party`** entirely (do not set **`null`** or a placeholder), so earlier rules can still supply **`dr-party`** without being overwritten.

**`review-messages`:** a **list of strings**, included **only when non-empty**. When present, entries are merged into the evaluation’s review list like other **`set.review-messages`** keys. Append messages when:

- **`amt`** (normalized to **`Decimal`**) **≠** the register cheque amount — message includes **both** amounts.
- **`date`** (calendar date) is **strictly before** the cheque **`issue_date`** — message includes **both** dates.

Persisting those messages on the journal entry is **[#89](https://github.com/brettski74/TallyBadger/issues/89)**; the bag still carries them for **`requires_review`** / review payload where implemented.

### On no match

The map **does not** include **`cheque-id`**, **`dr-account`**, **`summary`**, **`cheque-amount`**, or **`dr-party`**. It **must** include **`review-messages`** with **at least one** string (e.g. no open cheque for that account name and number, or unknown/inactive credit account name).

### Example

Activation exposes the row bag as **`attr`** and **`attributes`** (aliases); examples use **`attr`** for less typing.

```cel
{"set": cheque(attr["cr-account"], match[0]["list"][1], attr["amount"], attr["date"])}
```

The second argument is often a **string** capture (cheque number); it is coerced to an integer automatically.

---

## Generic helpers (**#50**)

These functions are registered on the same CEL **`Environment`** as **`party`** / **`cheque`** / **`debug`** / **`unset`**. They read the **current row attribute bag** where noted (`defined`), and **`account_type`** reads the **account snapshot** passed into `evaluate_cel` (from `list_accounts()` on **`POST /import-rules/cel/evaluate`** and CSV execute—**no per-cell DB calls** inside CEL).

### `abs(v) -> number`

- **Argument `v`:** A CEL **`int`**, **`uint`**, or **`double`**, or a **trimmed numeric string** (optional leading `-`; integers match `-?\\d+`, otherwise parsed as **`float`**).
- **Returns:** Absolute value. **`int` / `uint`** → **`int`**; **`double`** and numeric strings that are not integers → **`double`**. Attribute **`Decimal`** values are converted to **`double`** in the activation map before CEL sees them, so **`abs`** follows **double** semantics for those.
- **Errors:** Non-numeric types, blank numeric strings, or non-numeric strings → **`ImportRulesCelError`** (surfaced as CSV **`row_errors`** or evaluate **422** text).

### `day(d) -> int` / `month(d) -> int`

- **Argument `d`:** **`cel-python` `TimestampType`** (subclass of **`datetime`**), a Python **`date`** / **`datetime`** if it appears in the runtime, or a **non-blank** ISO **date** (`YYYY-MM-DD`) or **date-time** string (RFC3339-style; **`Z`** normalized for parsing). This matches how **`date`** / **`datetime`** attributes are usually exposed in CEL: as **ISO strings**.
- **Returns:** **`day`:** calendar **day-of-month 1–31**. **`month`:** **1–12**.
- **Calendar date:** For date-times, the **calendar date** is taken in the **parsed** instant’s offset (e.g. **`2026-04-09T22:00:00-05:00`** → **2026-04-09**). Naive strings use **`datetime.fromisoformat`** as documented for Python.
- **Errors:** **`null`**, blank string, or unsupported types → evaluation error.

### `decode(val, map, default) -> value`

- **Arguments:** **`val`** — lookup key; **`map`** — CEL **`map`** / object; **`default`** — value returned when there is no match.
- **Returns:** The **map entry value** for a string key equal to **`val`’s** usual string form (booleans → **`"true"`** / **`"false"`**; numbers → decimal string; doubles use integer string when whole). If the key is missing, returns **`default`**. If **`val`** is **`null`**, returns **`default`**. If **`map`** is not a map/object, returns **`default`** (no error).
- **Whitespace:** If the key is missing, a **second attempt** uses **`strip()`** on the string form of **`val`** only when that form differs from the non-stripped form.

### `defined(key) -> bool`

- **Argument `key`:** String **attribute name** (trimmed); blank key → **`false`**.
- **Returns:** **`true`** iff the attribute bag contains **`key`** and the value is **not** **`null`**, **not** Python **`None`** in the bag, and **not** the **empty string** (`""`). **Whitespace-only strings are not treated as empty** (they count as defined).
- **Semantics:** Reads the **mutable** bag for the row (so a **later** rule sees keys set by an **earlier** rule in the same evaluation).

### `account_type(str) -> string`

- **Argument `str`:** Canonical **account `name`** (trimmed; must match the stored name’s trim).
- **Returns:** One of **`asset`**, **`liability`**, **`equity`**, **`revenue`**, **`expense`**, **`suspense`** (same strings as **`AccountType`** / API).
- **Errors:** Blank name → evaluation error. **Unknown** name (not in the snapshot) or **inactive** account → evaluation error with an explicit message.

### `match_date(d, n, t) -> bool`

- **Arguments:** **`d`** — same accepted forms as **`day`** / **`month`** (calendar date only). **`n`** — target day-of-month, integer **1–31**. **`t`** — non-negative integer **tolerance** (days); **`double`** values must be **whole** numbers.
- **Returns:** Let **`dom`** be **`d`’s** day-of-month, **`dim`** = days in that month. **`low = max(1, n - t)`**, **`high = min(dim, n + t)`**. **`true`** iff **`low <= dom <= high`** (inclusive). **No** wrap into adjacent months.
- **Examples:** **2026-04-10:** `match_date(d, 8, 2)` → **`true`**; `match_date(d, 8, 1)` → **`false`**.
- **Errors:** Invalid **`n`** / **`t`**, or unparseable **`d`** → evaluation error.

---

## Changelog (maintenance)

| When | Change |
|------|--------|
| *(initial)* | Stub reference: #46 party helpers + #50 generic helpers split from monolithic #50 description. |
| *#46 ship* | `party()` returns **null** when no pattern matches; errors only on **multiple** matches. Party model, API, UI, and CEL wiring documented here. |
| *#46 follow-up* | **`equity_account(str)`** added as an alias of **`revenue_account(str)`** (same field and return value). |
| *#59 ship* | **`debug(x)`** — identity + ordered debug records; evaluate vs CSV `row_number` and JSON omission rules as above. |
| *#57 ship* | **`unset()`** — zero-arg marker for **`set`** map key removal; **`null`** still assigns **`None`**; trace **`remove_attribute`**. |
| *#57 follow-up* | CSV execute **422** **`row_errors[]`** may include **`debug`** (same shape as successful **`entries[]`**) when CEL ran before journal validation failed. |
| *#50 ship* | **`abs`**, **`day`**, **`month`**, **`decode`**, **`defined`**, **`account_type`**, **`match_date`** — stdlib-style helpers; **`evaluate_cel(..., accounts=)`** wires **`list_accounts()`** for evaluate + CSV. Engine walks CEL results for embedded **`CELEvalError`** values so **`ImportRulesCelError`** from custom functions (including **`party_*`**) surfaces as **`ImportRulesCelError`** / HTTP **422** instead of being left inside the **`set`** map. |
| *#92 ship* | **`cheque(account, nr, amt, date)`** — open-register map for **`set`**; **`evaluate_cel(..., cheques=)`** / CSV execute use **`list_cheques(status=open)`**; CSV maps **`cheque-id`** from the bag to **`JournalEntryWrite.cheque_id`**. |
| *#92 follow-up* | **`cheque-amount`** on match (register figure, string); **`nr`** accepts numeric strings; **`_cel_int_param`** accepts trimmed integer strings (also used by **`match_date`** day/tolerance). |

Update this table whenever functions are added or signatures/semantics change.
