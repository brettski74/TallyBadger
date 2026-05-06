# Implementation and pull request workflow

Use this workflow when building and shipping work for an agreed GitHub issue: plan first, then implement, test, and open a PR. It is **agent-agnostic** plain Markdown. Trust boundaries and data flows live in **[ARCH.md](../ARCH.md)**; tests, migrations, snapshot rules, and PR hygiene live in **[STYLE.md](../STYLE.md)**—apply those documents rather than copying them here.

## Pre-requisites

- A **fresh chat** dedicated to this implementation (avoid cross-ticket context from refinement or UAT unless this is explicitly the same ticket’s continuation after plan approval).
- The issue **number** `N` and repository context.
- **GitHub access** via **`user-github` MCP** (or equivalent) for issues and pull requests; **do not** rely on the `gh` CLI where it is unavailable.
- If the issue is **not** assigned to **`brettski74`**, set assignees when the API allows; otherwise assign manually in GitHub.
- Assume the issue is **open** unless the user directs otherwise.

## Steps

1. **Read** the issue (and any linked specs or comments needed to understand scope).
2. **Explain an implementation plan** to the user **before** editing application code, migrations, docs, or other tracked artefacts. Include what will change, main touchpoints, and how you will verify.
3. After the user **approves the plan**, implement following **[STYLE.md](../STYLE.md)** (tests, SQL migrations in the same PR when schema changes, backup/snapshot/format updates when applicable, and the consistency checklist there).
4. Work on a **feature branch**; do not land substantive work by committing directly to the default branch.
5. When implementation is ready, provide a **completion narrative**: what changed, any **architecture** impact (see **ARCH.md**), caveats, and which tests or docs moved.
6. After the user agrees the narrative is accurate: **commit**, **push**, and **open a pull request** that **links or closes** the issue using GitHub’s linking conventions (for example `Fixes #N` / `Closes #N` in the PR body), consistent with **[STYLE.md](../STYLE.md)**.

## Notes

- If scope drifts during implementation, pause and reconcile with the issue or run **refine.md** before piling on unrelated changes.
- The PR is the review surface; keep the issue updated only when the team wants cross-links, not as a substitute for the PR description.
