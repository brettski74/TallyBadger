# Requirements refinement workflow

Use this workflow when turning a **feature** GitHub issue into a single, agreed requirements document on GitHub. It is **agent-agnostic** plain Markdown. System boundaries and subsystem map live in **[ARCH.md](../ARCH.md)**; coding, testing, and delivery expectations live in **[STYLE.md](../STYLE.md)**—follow those files rather than duplicating them here.

## Pre-requisites

- A **fresh chat** dedicated to this refinement (do not reuse a thread that mixed another ticket’s implementation or UAT).
- The target issue **number** `N` and repository context (owner/repo or equivalent).
- **GitHub access** via **`user-github` MCP** (or equivalent API) for reading and updating issues when available; **do not** rely on the `gh` CLI where it is unavailable.
- If the issue is **not** assigned to the maintainer **`brettski74`**, set assignees via the GitHub API when the tools allow (for example `issue_write` with `assignees`); otherwise assign manually in the GitHub UI.
- Workflows assume the issue is **open**; if it is closed or marked duplicate, confirm with the user before proceeding.

## Steps

1. **Classify** the issue: this workflow targets **features**, not bugs. If the issue reads as a defect report or is misclassified, call that out and agree with the user whether to treat it as refinement (possibly after re-scoping) or hand off to another process before rewriting scope.
2. **Read** the issue (title, body, labels, and relevant comments) from GitHub.
3. **Draft** a fully detailed story: user voice, context, explicit **out of scope**, **acceptance criteria**, and risks/limitations/caveats. Ground it in **[ARCH.md](../ARCH.md)** and **[STYLE.md](../STYLE.md)** only by reference—do not paste long policy.
4. **Discuss gaps** with the user; revise the draft until the user agrees the requirements are complete.
5. **Update the issue body** on GitHub with the agreed text so the issue remains the **single source of truth** (for example `issue_write` with `method: update` and the new `body`).

## Notes

- Refinement ends with the **issue body** updated; long procedural detail stays in this file and in **STYLE.md** / **ARCH.md**, not duplicated across every comment.
- If requirements change materially later, either run this workflow again or treat the change as implementation detail per **implement.md**, as the team prefers.
