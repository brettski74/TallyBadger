## Summary

<!-- What changed and why (short, complete sentences). -->

## Issue tracking

<!-- Put the primary link here so it survives squash merge, e.g. Fixes #42 -->

Fixes #

## Verification

<!-- Commands run (e.g. make test), screenshots for UI. -->

## Consistency self-review

Canonical references: **[STYLE.md](../STYLE.md)** (how we build) and **[ARCH.md](../ARCH.md)** (shape of the system). Tick or strike rows that do not apply.

| Area | Applies to this PR | Done / N/A / notes |
|------|--------------------|--------------------|
| Database schema / domain model | Migrations or persisted shapes | |
| Backup / snapshot / import | Tables, FKs, ZIP layout, or restore behaviour | |
| Public API or stable JSON | Routes or client-visible JSON | |
| Architecture vs style | Boundaries/lifecycle vs conventions / testing / PR hygiene | |
| Feature-level domain docs | Behaviour documented under `docs/` | |
| Tests | All tests, including front-end, back-end, integration and any other automated tests, have been run and pass after all code changes and prior to merge. Include test result totals and execution times in PR body. |

If there is **no architecture change**, say so explicitly in the Summary or Verification section so reviewers skip ARCH.md churn.
