# Implementation and pull request workflow

Use this workflow when building and shipping work for an agreed GitHub issue: plan first, then implement, test, and open a PR. It is **agent-agnostic** plain Markdown. Trust boundaries and data flows live in **[ARCH.md](../ARCH.md)**; tests, migrations, snapshot rules, and PR hygiene live in **[STYLE.md](../STYLE.md)**—apply those documents rather than copying them here.

## Pre-requisites

- A **fresh chat** dedicated to this implementation (avoid cross-ticket context from refinement or UAT unless this is explicitly the same ticket’s continuation after plan approval).
- The issue **number** `N` and repository context.
- **GitHub access** via **`user-github` MCP**. If github MCP is unavailable or fails, abort and report the problem to the user.
- If the issue is **not** assigned to the current user, assign the issue to the current user.
- The issue must be **open**; if it is closed or marked duplicate, confirm with the user before proceeding.

## Steps

1. **Read** the issue (and any linked specs or comments needed to understand scope).
2. **Explain an implementation plan** to the user **before** editing application code, migrations, docs, or other tracked artefacts. Include what will change, main touchpoints, and how you will verify. Plan must be consistent with **[STYLE.md](../STYLE.md)** and **[ARCH.md](../ARCH.md)**. Do not change anything until the plan is approved. You need to stop here, present the plan and wait for approval!!!!!!! This is important. Do not pass this point in the workflow until you have approval from the user.
3. After the user **approves the plan**, implement in accordance with the agreed plan. If you encounter issues, discuss how to resolve with the user.
4. Work on a **feature branch**; do not land substantive work by committing directly to the default branch.
5. When implementation is ready, provide a **completion narrative**: what changed, any **architecture** impact (see **ARCH.md**), caveats, and which tests or docs moved.
6. After the user agrees the narrative is accurate: **commit**, **push**, and **open a pull request** that **links or closes** the issue using GitHub’s linking conventions (for example `Fixes #N` / `Closes #N` in the PR body), consistent with **[STYLE.md](../STYLE.md)**.

## Notes

- If scope drifts during implementation, pause and reconcile with the issue or run **refine.md** before piling on unrelated changes.
- The PR is the review surface; keep the issue updated only when the team wants cross-links, not as a substitute for the PR description.
- No user guidance provided before presentation of the implementation plan can ever be used as approval to proceed with any implementation. The implementation plan must always be presented and approval for the plan must be explicitly received from the user after presentaton of the plan. Any user guidance provided prior to presentation of the implementation plan can only be used to help inform what the implementation plan should be.
