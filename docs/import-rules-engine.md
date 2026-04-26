# Import rules engine (GitHub [#8](https://github.com/brettski74/TallyBadger/issues/8))

This document describes **what is implemented today**: behaviour, API, JSON shapes, tests, and **gaps**. There is **no frontend** for rules in this pass; use `/docs` or pytest.

---

## Import template vs rules engine (separation of duties)

| Stage | Responsibility |
|--------|------------------|
| **Import template** (future UI / #9) | Map source columns → **canonical attribute names**; run **simple, deterministic conversions** (e.g. strip currency symbols, parse amounts to numbers, parse date strings to dates). Same logical field names and types across banks → **one rule set can be reused** with different templates. |
| **Rules engine (#8)** | Take that **bag of attributes** (mixed types). **Match** rows and **enrich** them: regex captures, copies, numeric checks, ordered overwrites, `append_to_attribute` to build strings, etc. Output: **same bag shape**, larger or richer. |
| **JE readiness** (later) | Check the bag for **everything needed** to build a journal entry; if incomplete, surface **missing fields** or hand off for user fix / drop. |
| **Posting** | Create ledger entries from a complete bag (#10 / ledger). |

The engine **does not** read CSV, own column mapping, or post journals. It only runs **`evaluate(rule_set, attributes)`**.

---

## Pydantic: what it is here

**Pydantic** validates and parses **HTTP JSON** and in-memory structures (e.g. rule definitions): required fields, discriminated `type` tags on matchers/actions, string lengths. It is **not** a substitute for your template layer—it does **not** replace “map this bank column to `posted_on`.” It helps keep **API and `RuleSet` payloads** well-formed.

The **attribute bag** is modeled as `dict[str, Any]`: after JSON parsing you typically see `str`, `int`, `float`, `bool`, and `null`. For **money**, JSON has no `Decimal`; prefer **strings** in JSON if you need exact decimal semantics, or accept `float` knowing the limitations. In-process Python callers can pass `datetime`, `date`, `Decimal`, etc.; matchers use helpers to interpret them.

---

## Code layout

| Path | Purpose |
|------|---------|
| `src/tallybadger/import_rules/models.py` | `RuleSet`, `Rule`, matchers, actions, `EvaluationResult`, `TraceEvent` |
| `src/tallybadger/import_rules/engine.py` | `evaluate(rule_set, attributes)` |
| `src/tallybadger/import_rules/errors.py` | `ImportRulesError` |
| `src/tallybadger/api/routes/import_rules.py` | `POST /import-rules/evaluate` |
| `tests/test_import_rules_engine.py` | Unit tests |
| `tests/test_import_rules_api.py` | API tests |

---

## Typed attribute bag (no blanket string coercion)

1. **Input** — Shallow copy of `attributes`. **Scalars** are kept as-is (`int`, `float`, `str`, `bool`, `None`). **`list` / `dict`** values are shallow-copied with `copy.copy` so rules do not mutate the caller’s nested objects by accident.
2. **`set_attribute`** — `literal_value` may be any JSON-scalar or structure; `from_attribute` copies the referenced value (same typing); `from_regex_group` always produces a **string** (capture text).
3. **`append_to_attribute`** — Each piece is turned into a string fragment (`_display_for_concat`: dates → ISO date, `Decimal` → plain `format`, numbers → `str`, etc.). The **stored attribute is always a `str`** after append.

---

## Evaluation semantics

1. **Rule order** — `(sort_order, original list index)`.
2. **Disabled rules** — Skipped; `rule_skipped` in trace.
3. **Matchers** — All must pass (**AND**). **Empty `matchers`** ⇒ rule always matches.
4. **Regex** — `re.search` on **`str(attribute value)`** (regex is inherently text).
5. **Actions** — Run only if the rule matched, in order. Later steps may **overwrite** keys unless you **`stop`** first.
6. **Actions are first-class** — `stop`, `drop_row`, and `require_review` are normal actions from the author’s perspective. Implementation-wise:
   - **`stop`** — stop processing **further rules** (only runs if this rule matched).
   - **`drop_row`** — set `dropped`, optional reason, stop further rules.
   - **`require_review`** — set `require_review` / `review_reason` only; **does not** stop later rules or matchers (a later rule can still run).
7. **Trace** — See [Trace events](#trace-events).

---

## Matchers (`type` discriminator)

| `type` | Notes |
|--------|--------|
| `regex` | `str(value)` as haystack. Capture groups available to actions on this rule via `from_regex_group`. |
| `equals` / `not_equals` | Compare attribute to rule `value` **string** using typed helpers: if both parse as `Decimal`, numeric compare; if attribute is `date` / ISO `str`, date compare; else string compare (`case_insensitive` where relevant). |
| `contains` | Substring on `str(attribute)`. |
| `numeric_compare` | Attribute coerced via `Decimal` rules (`int` ok; `bool` ignored as number). |
| `in_set` | True if attribute equals **any** list entry under the same rules as `equals` (per-element). |
| `day_of_month` / `day_of_week` | Attribute as `date`, `datetime`, or ISO `YYYY-MM-DD` string. |

---

## Actions (`type` discriminator)

| `type` | Notes |
|--------|--------|
| `set_attribute` | Exactly one of: `literal_value` (any JSON-compatible / Python value), `from_attribute`, `from_regex_group` (string). |
| `append_to_attribute` | Same three sources as fragments; **resulting attribute is a string**. Chain multiple `append_to_attribute` steps in one rule to build e.g. `"{date} {tenant} Rent"`. |
| `stop` | Stop further rules. |
| `drop_row` | Mark dropped + reason; stop further rules. |
| `require_review` | Flags only; processing continues. |

### `from_regex_group`

```json
{ "matcher_index": 0, "group": "sender" }
```

`group` may be a **1-based** integer or a **named** group. `matcher_index` indexes this rule’s `matchers` array (the entry must be `regex` and must have matched).

---

## Future: safe expression language (not implemented)

A **single** `set_attribute` could someday take a **limited expression** (attribute names as variables, `match[matcherIndex][group]`, string concat, basic math, `upper`/`lower`/title case) with **no** arbitrary Python/JS execution. A common pattern is **[CEL](https://github.com/google/cel-spec)** (`cel-python`) or a **small custom AST** evaluated in a sandbox. That would reduce long chains of `append_to_attribute` for complex labels. **Tracking:** extend [#8](https://github.com/brettski74/TallyBadger/issues/8) or a child issue when you prioritise it.

---

## HTTP API

**`POST /import-rules/evaluate`**

- **`attributes`**: object with **any JSON values** (strings, numbers, booleans, null, nested arrays/objects if you pass them—matchers mostly use scalars).
- **`rule_set`**: ordered rules as in the examples below.

```json
{
  "attributes": {
    "description": "EMT - ACME, ref 1",
    "amount": 100.0
  },
  "rule_set": {
    "rules": [
      {
        "id": "emt-sender",
        "sort_order": 10,
        "enabled": true,
        "matchers": [
          {
            "type": "regex",
            "attribute": "description",
            "pattern": "EMT\\s*-\\s*(?P<sender>[^,]+),",
            "flags": []
          }
        ],
        "actions": [
          {
            "type": "set_attribute",
            "name": "party_name_hint",
            "from_regex_group": { "matcher_index": 0, "group": "sender" }
          }
        ]
      }
    ]
  }
}
```

Response **`EvaluationResult`**: `attributes` (typed bag), `dropped`, `drop_reason`, `require_review`, `review_reason`, `stopped_after_rule`, `trace`.

`ImportRulesError` → **422** with `detail` text.

Interactive: **`/docs`** → **import-rules**.

---

## Trace events (non-exhaustive)

| `event` | Typical `detail` |
|---------|------------------|
| `rule_skipped` | `rule`, `reason` |
| `rule_tried` / `rule_not_matched` / `rule_matched` | `rule` |
| `set_attribute` | `rule`, `name`, `value` (value may be non-string) |
| `append_to_attribute` | `rule`, `name`, `fragment` |
| `stop` | `rule` |
| `drop_row` | `rule`, `reason` |
| `require_review` | `rule`, `reason` |

---

## Tests

- **`make test-unit`** — all non-integration tests (includes import rules).
- **`make test`** — full suite + DB + integration; **`test-results/pytest.html`**.

---

## Not implemented yet (checklist)

- [ ] Persisted **import templates** / profiles and **stored rule sets**; CRUD; SQL migrations.
- [ ] **Frontend**: template editor, rule wizard, test bench.
- [ ] **OR / nested matcher groups** (only AND within a rule).
- [ ] **Post-rules JE completeness** module.
- [ ] **CSV import (#9)** and **posting (#10)** wired to `evaluate`.
- [ ] **Safe expression language** for `set_attribute` (optional).

---

## Calling from Python

```python
from datetime import date
from decimal import Decimal

from tallybadger.import_rules import Rule, RuleSet, evaluate
from tallybadger.import_rules.models import SetAttributeAction

out = evaluate(
    RuleSet(rules=[Rule(matchers=[], actions=[SetAttributeAction(name="x", literal_value=1)])]),
    {"amount": Decimal("10.00"), "posted_on": date(2026, 4, 1)},
)
assert out.attributes["x"] == 1
assert out.attributes["amount"] == Decimal("10.00")
```

---

## References

- [#8 – Pattern and rules engine for transaction categorization during ingest](https://github.com/brettski74/TallyBadger/issues/8)
- OpenAPI: `/docs`

---

## CEL spike (alternative rule model)

There is now a **spike implementation** that models each rule as one CEL expression, with optional regex capture pre-step:

- Engine: `src/tallybadger/import_rules/cel_engine.py`
- Models: `src/tallybadger/import_rules/cel_models.py`
- API: `POST /import-rules/cel/evaluate` via `src/tallybadger/api/routes/import_rules_cel.py`
- Tests: `tests/test_import_rules_cel_engine.py`, `tests/test_import_rules_cel_api.py`

### CEL rule contract (spike)

Each rule has:

- `expression`: CEL expression
- optional `captures`: list of regex specs to precompute `match`/`matches` activation values

The expression should return either:

- `null` -> treated as **no match**
- map/object -> treated as **matched action payload**

Top-level reserved payload keys:

- `set`: map of attribute updates
- `stop`: `null` or **string reason** (non-null string stops further rules)
- `drop`: `null` or **string reason** (non-null string drops row + stops)
- `review`: `null` or **string reason** (non-null string marks require-review; processing continues)

This reflects the compromise design: control flags are top-level; mutable attributes are namespaced under `set`.

### Example CEL expression

```cel
match[0]["ok"]
  ? {
      "set": {
        "party_name_hint": match[0]["groups"]["sender"],
        "label": string(attributes["posted_on"]) + " " + match[0]["groups"]["sender"] + " Rent"
      },
      "review": "confirm sender match",
      "stop": null,
      "drop": null
    }
  : null
```

### Notes

- In this spike, non-map/non-null expression results are treated as **no match**.
- `stop/drop/review` must be null or string; other types return 422 via `ImportRulesCelError`.
- `append_to_attribute` is not needed in CEL mode; string composition is done directly in expression.
