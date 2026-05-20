# User acceptance testing and fix loop workflow

Use this workflow for **user-led acceptance testing** after implementation exists (typically on a feature branch or after deployment to a test environment). The chat clarifies behaviour, suspected bugs, or gaps versus the agreed issue. It is **agent-agnostic** plain Markdown. Product and trust boundaries remain in **[ARCH.md](../ARCH.md)**; delivery expectations remain in **[STYLE.md](../STYLE.md)**.

## Pre-requisites

- A **fresh chat** focused on UAT for this issue (avoid mixing unrelated tickets).
- The issue **number** `N`, the branch or build under test, and repository context.
- **GitHub access** via `**user-github` MCP**. If github MCP is unavailable or fails, abort and report the problem to the user.
- If the issue is **not** assigned to the current user, assign the issue to the current user.
- The issue must be **open**; if it is closed or marked duplicate, confirm with the user before proceeding.

## Steps

1. **Confirm** what the user is testing (environment, branch, PR, or release) and the acceptance criteria from the issue then stop and wait for further instructions from the user.
2. Support **user-led** testing: answer questions, reproduce reported behaviour, and distinguish expected versus defective behaviour using the issue and **[ARCH.md](../ARCH.md)** as reference.
3. If the user reports a **bug** or **requirement gap**, fix code or docs as agreed and **record** the gap and resolution in **issue comments** (not by rewriting the issue body). Reserve body edits for explicit **refinement**—if the user wants the requirements document itself changed, suggest that the user switch to the **refine** workflow in a fresh chat. Do not rewrite the issue body while within this workflow.
4. **Commit** and **push** fixes on the **same feature branch** as the implementation under test until UAT is complete. Remind the user that you are waiting for them to confirm when the merge is done before performing final cleanup and switching back to the main branch.
5. When the user **explicitly says** the PR is **merged** (or integration to the default branch is complete **on their side**): **check out** the default branch, **pull** latest, and treat the workspace as ready for the next piece of work. This step is **not** “the assistant merges the PR”; it is **sync local git after the human merged**. The feature branch will be deleted remotely when the branch is merged. Ensure that the same thing happens on the local repo.

## Notes

- UAT is not the place to silently broaden scope; capture product decisions in comments or run **refine.md** when the specification must change.
- If a gap is purely operational (data, config), document it in comments and fix procedures or README as appropriate without changing the issue’s acceptance story unless the user asks.
- The user may initiate this workflow with just `!wk-ship #<number>` (see **STYLE.md**). This does not signal anything more than they are about to start performing UAT.
- Work on one issue at a time and review the solution with the user before implementing it.
- Design and implement tests before implementing to solution to any reported issues.
- Commit any unsaved prior work before starting work on a new issue.

