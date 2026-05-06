# User acceptance testing and fix loop workflow

Use this workflow for **user-led acceptance testing** after implementation exists (typically on a feature branch or after deployment to a test environment). The chat clarifies behaviour, suspected bugs, or gaps versus the agreed issue. It is **agent-agnostic** plain Markdown. Product and trust boundaries remain in **[ARCH.md](../ARCH.md)**; delivery expectations remain in **[STYLE.md](../STYLE.md)**.

## Pre-requisites

- A **fresh chat** focused on UAT for this issue (avoid mixing unrelated tickets).
- The issue **number** `N`, the branch or build under test, and repository context.
- **GitHub access** via **`user-github` MCP** (or equivalent) for comments and, when needed, PR reads; **do not** rely on the `gh` CLI where it is unavailable.
- If the issue is **not** assigned to **`brettski74`**, set assignees when the API allows; otherwise assign manually.
- Assume the issue is **open** for tracking UAT unless the user says otherwise.

## Steps

1. **Confirm** what the user is testing (environment, branch, PR, or release) and the acceptance criteria from the issue.
2. Support **user-led** testing: answer questions, reproduce reported behaviour, and distinguish expected versus defective behaviour using the issue and **[ARCH.md](../ARCH.md)** as reference.
3. If the user reports a **bug** or **requirement gap**, fix code or docs as agreed and **record** the gap and resolution in **issue comments** (not by rewriting the issue body). Reserve body edits for explicit **refinement**—if the user wants the requirements document itself changed, switch to the **refine** workflow (`/refine #N` as documented in **STYLE.md**).
4. **Commit** and **push** fixes on the **same feature branch** as the implementation under test until UAT is complete.
5. When the user signals **merge is done** on the PR: **check out** the default branch, **pull** latest, and treat the workspace as ready for the next piece of work.

## Notes

- UAT is not the place to silently broaden scope; capture product decisions in comments or run **refine.md** when the specification must change.
- If a gap is purely operational (data, config), document it in comments and fix procedures or README as appropriate without changing the issue’s acceptance story unless the user asks.
