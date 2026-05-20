# Import rules engine — CEL and regex captures ([#8](https://github.com/brettski74/TallyBadger/issues/8), doc refresh [#94](https://github.com/brettski74/TallyBadger/issues/94))

This document describes the **import rules path that exists in production for bank CSV import**: **CEL** expressions, optional **ordered regex captures**, **`evaluate_cel`**, persisted **CEL rule sets**, and the HTTP routes that invoke them. Use **OpenAPI** at **`/docs`** for request and response schemas.

**Related:** [CEL function reference](cel-function-reference.md) — custom helpers (`debug()`, `unset()`, `party()`, `cheque()`, …). **[ARCH.md](../ARCH.md)** — where CSV import sits in the system (trust boundaries, high-level flow).

**Frontend:** the SPA **Import rules** tab runs **`CelRuleSetsSection`** ([`frontend/src/components/CelRuleSetsSection.tsx`](../frontend/src/components/CelRuleSetsSection.tsx)) — create, edit, and delete persisted CEL rule sets (name, rule order, captures, expressions). CSV import can attach a rule set by id. Authors can still use **`/docs`** or **`POST /import-rules/cel/evaluate`** for ad-hoc evaluation without saving.

---

## Repository note: matcher/action engine (not used by CSV import)

The tree still contains an **older** rules model: **ordered rules** made of **matchers** (e.g. regex, equals) and **actions** (e.g. `set_attribute`, `append_to_attribute`, `stop`, `drop_row`, `require_review`). That path is **not** called from **`POST /imports/csv/execute`**; CSV import uses **`evaluate_cel`** only.

**Inventory (for a future cleanup / usage audit — not part of [#94](https://github.com/brettski74/TallyBadger/issues/94)):**

| Location | Role |
|----------|------|
| [`src/tallybadger/import_rules/models.py`](../src/tallybadger/import_rules/models.py) | Pydantic types: `RuleSet`, `Rule`, matcher and action discriminated unions, `EvaluationResult`, `TraceEvent`. |
| [`src/tallybadger/import_rules/engine.py`](../src/tallybadger/import_rules/engine.py) | `evaluate(rule_set: RuleSet, attributes: dict[str, Any]) -> EvaluationResult` — runs matcher/action rules in sort order. |
| [`src/tallybadger/api/routes/import_rules.py`](../src/tallybadger/api/routes/import_rules.py) | **`POST /import-rules/evaluate`** — stateless JSON API wrapping `evaluate`. Still **mounted** from [`main.py`](../src/tallybadger/main.py). |
| [`src/tallybadger/import_rules/errors.py`](../src/tallybadger/import_rules/errors.py) | `ImportRulesError` (matcher path) and `ImportRulesCelError` (CEL path). |
| [`src/tallybadger/import_rules/__init__.py`](../src/tallybadger/import_rules/__init__.py) | Public re-exports of **both** `evaluate` and `evaluate_cel`, plus matcher and CEL model types. |
| [`tests/test_import_rules_engine.py`](../tests/test_import_rules_engine.py) | Unit tests for `evaluate`. |
| [`tests/test_import_rules_api.py`](../tests/test_import_rules_api.py) | HTTP tests for **`POST /import-rules/evaluate`**. |

**Known usage today:** tests and the **`POST /import-rules/evaluate`** endpoint only (no import pipeline integration). Removing or consolidating this code would require a deliberate decision, client impact check, and test updates.

---

## End-to-end flow (CSV)

1. Client sends **`POST /imports/csv/execute`** with CSV text, column → attribute mapping, optional **`cel_rule_set_id`**, and template options.
2. Each **data** row is turned into an **attribute bag** (typed values from cells — see route validation / converters in [`import_csv.py`](../src/tallybadger/api/routes/import_csv.py)).
3. If a CEL rule set is configured, the row bag is passed to **`evaluate_cel`** (stored definition loaded by id). Otherwise the bag is unchanged by rules.
4. The bag is converted to a **`JournalEntryWrite`** (summary, lines, review flags, optional cheque link). Rows **dropped** by CEL never become journal entries.
5. Entries are posted through the ledger service (see ARCH.md).

**Stateless try-out:** **`POST /import-rules/cel/evaluate`** accepts a rule set and bag in the body — no CSV, no persistence required.

---

## Persisted CEL rule sets

CEL rule sets can be stored in the database and referenced by id from CSV execute.

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/import-rules/cel/rule-sets` | List ids, names, `updated_at`. |
| `POST` | `/import-rules/cel/rule-sets` | Create (name + `CelRuleSet` JSON). |
| `GET` | `/import-rules/cel/rule-sets/{id}` | Fetch one. |
| `PATCH` | `/import-rules/cel/rule-sets/{id}` | Update name and/or rule set body. |
| `DELETE` | `/import-rules/cel/rule-sets/{id}` | Delete. |

Implementation: [`cel_rule_sets.py`](../src/tallybadger/api/routes/cel_rule_sets.py), [`cel_rule_set_service.py`](../src/tallybadger/import_rules/cel_rule_set_service.py).

---

## CEL rule set model

Types live in [`cel_models.py`](../src/tallybadger/import_rules/cel_models.py).

- **`CelRuleSet`** — `rules: list[CelRule]`.
- **`CelRule`** — `name` (optional), `enabled`, `sort_order`, **`expression`** (CEL source string), **`captures`** (optional ordered list of `CelRegexCapture`).
- **`CelRegexCapture`** — `attribute` (bag key), `pattern`, `flags` (`ignorecase`, `multiline`, `dotall`), optional `label`.

Rules are processed in order by **`(sort_order, original index)`**. Disabled rules are skipped.

---

## Ordered captures and activation

For each rule, **`captures`** run **in list order** before the CEL **`expression`**:

1. For each capture, the engine runs `re.search(pattern, str(bag[attribute]), flags)` (empty/missing attribute → empty string).
2. On the **first** failed capture, the rule is a **no-match**: no expression run, trace records `rule_not_matched` with `reason: capture_failed` and the capture index.
3. If all captures succeed (or the list is empty), the engine builds **`match`** / **`matches`** and evaluates **`expression`**.

**Activation map** passed to CEL (same content surfaced under two names for ergonomics):

| Key | Meaning |
|-----|---------|
| `attributes`, `attr` | Current attribute bag (maps). |
| `match`, `matches` | List of capture results; **`match[i]`** corresponds to **`captures[i]`**. |

Each capture result is a map with `ok`, `whole`, `list` (index `0` = full match, `1…n` = numbered groups), and `groups` (named captures). When the expression runs, every listed capture has **`ok: true`** (failed captures never reach the expression).

---

## Rule result payload (matched rule)

If the expression returns **`null`**, the rule does not match. Any other non-map result is a **422** (`ImportRulesCelError`). If it returns a **map**, it is the **payload**.

### `set`

Map of attribute updates applied **in iteration order**. Values are merged into the bag. Use the CEL **`unset()`** helper as a value to **remove** a key (see [CEL function reference](cel-function-reference.md#unset--remove-a-key-from-the-attribute-bag-57)). **`null`** sets the key to JSON null but **does not** remove it.

Keys **`review`** and **`review-messages`** inside **`set`** are **not** normal bag keys: they are handled like top-level review fields (see below), appended to the run’s review list, and **not** left in the bag.

### `stop` and `drop`

- **`stop`**: must be **`null`** or a **string**. If it is **not `null`**, rule processing **stops** after this rule (later rules do not run). The string is recorded on the result as the stop reason for tracing.
- **`drop`**: must be **`null`** or a **string**. If it is **not `null`**, the row is **dropped** (no journal entry), processing ends, and the string is the drop reason.

Types other than `null` or `string` are rejected.

### `review` and `review-messages` (aligned with [#89](https://github.com/brettski74/TallyBadger/issues/89))

These fields express **why a row may need human review**. They are **not** durable bag attributes: the engine **strips** `review` and `review-messages` from the bag after each matched rule and after the full run.

**Top-level** (on the payload map) or **inside `set`** (same semantics):

- **`review`**: **`null`** or a **string**. If it is a string, it must be **non-empty** after trim; otherwise **422**. Each valid value **appends one** message to the run’s **`review_messages`** list.
- **`review-messages`**: **`null`** or a **list**. Each element must be a **string** (or **`null`**, which is skipped); non-strings **422**. Each **non-empty** string after trim **appends** one message.

**Accumulation:**

- Messages are collected in **rule application order** (only from rules that matched and returned a payload).
- Later rules **append**; they do **not** replace earlier reasons.
- The CSV path passes the final **`review_messages`** into journal construction so **`requires_review`** is set when the list is non-empty.

For **author diagnostics**, prefer **`debug(x)`** in expressions ([`debug()` in the function reference](cel-function-reference.md#debugx--inspection-helper-59)); it records values without changing rule outcome.

---

## Evaluation result (`CelEvaluationResult`)

Returned by **`evaluate_cel`** and **`POST /import-rules/cel/evaluate`**:

- **`attributes`** — final bag.
- **`dropped`**, **`drop_reason`** — set when a rule returned **`drop`**.
- **`review_messages`** — ordered strings from **`review`** / **`review-messages`**.
- **`stopped_after_rule`** — label of the rule that stopped processing, if any.
- **`trace`** — list of **`CelTraceEvent`** (`event` + `detail`). This is an **internal step log** in API JSON (rule tried/matched/skipped, `set_attribute`, `remove_attribute`, review events, `stop`, `drop_row`, etc.). It is **not** the primary authoring tool; use **`debug()`** to inspect values while writing rules.
- **`debug`** — optional array of **`debug()`** records; omitted when empty.

---

## Automatic review after CEL (journal construction)

[`import_csv.py`](../src/tallybadger/api/routes/import_csv.py) merges CEL **`review_messages`** with reasons added while building journal lines from the bag, for example:

- **Unallocated debits / credits** — when the simple amount path falls back to ledger **suspense** accounts configured as unallocated targets, messages such as *“The debit amount is unallocated.”* / *“The credit amount is unallocated.”* are appended.
- **`require_review`** on the bag — when truthy (from rules or column mapping), an additional explanatory string may be appended.

Exact wording and conditions are defined in **`_bag_to_journal_entry`** and **`_build_lines_from_simple`** in the same module.

---

## `line[]` journal lines and obligation settlement ([#151](https://github.com/brettski74/TallyBadger/issues/151))

CEL rules (or column mapping) may set a **`line`** attribute: a list of maps that become journal lines. Each map:

| Key | Required | Meaning |
|-----|----------|--------|
| `account` | yes | Account name (must exist and be active) |
| `amount` | yes | Signed GL amount; all lines must balance to zero |
| `party` | no | Party name |
| `obligation-id` | no | When set, **`|amount|`** is applied to that `accrual_obligations.id` |

Rules:

- **`obligation-id` absent** — normal journal line only (e.g. cash leg).
- **`obligation-id` present** — settlement required; applied amount = **`|amount|`** (must be &gt; 0).
- **Partial:** `|amount| &lt; open_amount` on that obligation → obligation becomes `partially_settled`; a separate import journal entry is posted.
- **Full:** `|amount| == open_amount`.
- **Multi-obligation:** multiple lines, each with its own id.
- **Remainder / overpay:** lines **without** `obligation-id` (e.g. unearned or revenue) — prevents exact same-day collapse when present alongside a full obligation line.

Receipt settlements use the **accounts receivable** bridge (negative amount on A/R); payments use **accounts payable** (positive amount on A/P). Row validation rejects unknown obligations, duplicate ids on one entry, amounts exceeding `open_amount`, party mismatch, and wrong bridge account or sign.

Posting (in `create_import_batch_with_entries`, same transaction as the journal insert):

1. Collect **`obligation-id`** lines and build allocations with amount **`|amount|`**.
2. **Exact same-day collapse** (import-only, stricter than manual “same accrual day”): exactly one obligation line, full pay, row **`date`** equals accrual **`entry_date`**, and the import row is exactly **cash + bridge reduction** (two lines). The accrual journal entry is rewritten in place, stamped with **`import_batch_id`**, and **`settlement_allocations`** point at that accrual entry — no separate import JE.
3. Otherwise: insert the import journal entry from **`line[]`**, insert **`settlement_allocations`** with `entry_id` = that JE, apply early-receipt reclassification when applicable, and update obligation balances.

**Import batch unload** reverses allocations whose `entry_id` belongs to the batch (including collapsed accrual entries), restores obligation `open_amount`, and clears **`import_batch_id`** on plan accrual entries. See [ledger data model](ledger-data-model.md#import-batch-unload--discovery-and-scope).

Example (full receipt, separate JE — catch-up date):

```json
"line": [
  {"account": "Cash", "amount": "1500.00", "party": "Pamela Tenant"},
  {"account": "Accounts Receivable", "amount": "-1500.00", "party": "Pamela Tenant", "obligation-id": 42}
]
```

Example (exact same-day collapse — only cash + one obligation line, date matches accrual):

```json
"line": [
  {"account": "Cash", "amount": "500.00", "party": "Tenant Unload"},
  {"account": "Accounts Receivable", "amount": "-500.00", "party": "Tenant Unload", "obligation-id": 7}
]
```

The optional top-level **`settlement`** auto-build attribute ([#152](https://github.com/brettski74/TallyBadger/issues/152)) is **not** required when authors supply **`line[]`** with **`obligation-id`**.

---

## `settlement` auto-build attribute ([#152](https://github.com/brettski74/TallyBadger/issues/152))

After CEL and **import default account** resolution, the CSV path may set **`settlement`** to **`receipt`** or **`payment`**. The engine matches open obligations, allocates **FIFO** (`source_entry_date`, then `id`), synthesizes **`line[]`** (cash + A/R or A/P bridges with **`obligation-id`**), and posts through the [#151](https://github.com/brettski74/TallyBadger/issues/151) import settlement path.

| `settlement` | Behaviour |
|--------------|-----------|
| `receipt` | Auto-build receivable settlement `line[]` |
| `payment` | Auto-build payable settlement `line[]` |
| unset / null | No auto-settlement (unchanged) |

### Mutual exclusion

If **`settlement`** is `receipt` or `payment` **and** the bag already has **`line[]`** → row **422** (*settlement cannot be used together with line[]*).

### Preconditions (else simple journal + review)

**Receipt:** `cr-party`, `cr-account` (P&amp;L hint, e.g. Rent Revenue); `dr-account` is **asset** or **liability** (cash/bank); `amount`, `date`, `summary`; accounts receivable configured in ledger settings.

**Payment:** `dr-party`, `dr-account` (P&amp;L hint); `cr-account` is **asset** or **liability**; `amount`, `date`, `summary`; accounts payable configured.

Both `dr-account` and `cr-account` must be present after import defaults (no unallocated suspense fallback for the settlement attempt).

### FIFO matching

Open obligations for the party where the accrual plan **`target_account_id`** equals the P&amp;L hint account (`cr-account` for receipts, `dr-account` for payments), type **receivable** or **payable**, ordered by accrual **`source_entry_date`** then **`id`**.

### Auto-built outcomes

| Case | Behaviour |
|------|-----------|
| Fully allocated | Cash + bridge lines only |
| Receipt overpay / no more obligations | Remainder on **`cr-account`** (P&amp;L hint) + **review** (not unearned revenue) |
| Payment overpay | Remainder on **`dr-account`** + **review** |
| No matching obligations | Simple journal from bag + **review** |
| Preconditions fail | Simple journal + **review** |

Review messages are merged with CEL **`review_messages`** and other import review reasons.

### Authoring example (Pamela rent receipt)

```cel
{
  "set": {
    "settlement": "receipt",
    "summary": "Pamela rent",
    "amount": attr["amt"],
    "date": attr["date"],
    "cr-account": "Rent Revenue",
    "cr-party": "Pamela Person"
  }
}
```

(`dr-account` comes from the template **`default_import_account_id`** — e.g. chequing — before matching.)

---

## HTTP quick reference

| Endpoint | Role |
|----------|------|
| **`POST /import-rules/cel/evaluate`** | Run a **`CelRuleSet`** from the request body against **`attributes`**; optional **`debug`** in response. |
| **`POST /imports/csv/execute`** | Import CSV; optional **`cel_rule_set_id`** loads a stored set and runs **`evaluate_cel`** per row. |
| **`POST /import-rules/evaluate`** | Matcher/action **`evaluate`** only — see [repository note](#repository-note-matcheraction-engine-not-used-by-csv-import) above. **Not** part of the CSV pipeline. |

---

## Code index (CEL path)

| Path | Purpose |
|------|---------|
| [`cel_engine.py`](../src/tallybadger/import_rules/cel_engine.py) | **`evaluate_cel`**, capture gating, payload handling, trace/debug. |
| [`cel_models.py`](../src/tallybadger/import_rules/cel_models.py) | `CelRuleSet`, `CelRule`, `CelRegexCapture`, `CelEvaluationResult`, `CelTraceEvent`, `CelDebugEvent`. |
| [`import_rules_cel.py`](../src/tallybadger/api/routes/import_rules_cel.py) | **`POST /import-rules/cel/evaluate`**. |
| [`import_csv.py`](../src/tallybadger/api/routes/import_csv.py) | **`POST /imports/csv/execute`**, bag → journal, CEL integration. |
| [`cel_party_functions.py`](../src/tallybadger/import_rules/cel_party_functions.py), [`cel_stdlib_functions.py`](../src/tallybadger/import_rules/cel_stdlib_functions.py), [`cel_cheque_functions.py`](../src/tallybadger/import_rules/cel_cheque_functions.py) | Registered CEL functions. |

---

## Tests

- **`tests/test_import_rules_cel_engine.py`** — `evaluate_cel` behaviour.
- **`tests/test_import_rules_cel_api.py`** — **`POST /import-rules/cel/evaluate`**.
- CSV + CEL integration: search under **`tests/`** for **`csv/execute`**, **`import_csv`**, or **`cel_rule_set`** (names may evolve).

---

## References

- [#8](https://github.com/brettski74/TallyBadger/issues/8) — import rules (CEL path is the shipped import story).
- [#37](https://github.com/brettski74/TallyBadger/issues/37) — persisted CEL rule sets (historical tracking; behaviour is current).
- [#57](https://github.com/brettski74/TallyBadger/issues/57) — `unset()` in **`set`**.
- [#59](https://github.com/brettski74/TallyBadger/issues/59) — `debug()`.
- [#73](https://github.com/brettski74/TallyBadger/issues/73) — parent cheque/import workstream.
- [#89](https://github.com/brettski74/TallyBadger/issues/89) — review message contract (accumulation, bag stripping).
- [#92](https://github.com/brettski74/TallyBadger/issues/92) — `cheque()` and CSV cheque wiring.
- [#94](https://github.com/brettski74/TallyBadger/issues/94) — this documentation rewrite.
