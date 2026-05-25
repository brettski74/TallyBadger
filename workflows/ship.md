# User acceptance testing and fix loop workflow

Use this workflow for **user-led acceptance testing** after implementation exists (typically on a feature branch or after deployment to a test environment). The chat clarifies behaviour, suspected bugs, or gaps versus the agreed issue. It is **agent-agnostic** plain Markdown. Product and trust boundaries remain in **[ARCH.md](../ARCH.md)**; delivery expectations remain in **[STYLE.md](../STYLE.md)**.

## Pre-requisites

- A **fresh chat** focused on UAT for this issue (avoid mixing unrelated tickets).
- The issue **number** `N`, the branch or build under test, and repository context.
- **GitHub access** via `**user-github` MCP**. If github MCP is unavailable or fails, abort and report the problem to the user.
- If the issue is **not** assigned to the current user, assign the issue to the current user.
- The issue must be **open**; if it is closed or marked duplicate, confirm with the user before proceeding.

## Steps

1. **Setup the environment for testing** by running `make ship-prepare` to ensure that the environment is cleanly loaded and restarted.
2. **Confirm** from the code changes, ticket details and acceptance criteria what the user is testing. Display a suggested testing checklist for the user in the chat, then stop and wait for further instructions from the user.
3. Support **user-led** testing: answer questions, reproduce reported behaviour, and distinguish expected versus defective behaviour using the issue and **[ARCH.md](../ARCH.md)** as reference.
4. If the user reports a **bug** or **requirement gap**, fix code or docs as agreed and **record** the gap and resolution in **issue comments** (not by rewriting the issue body). Reserve body edits for explicit **refinement**—if the user wants the requirements document itself changed, suggest that the user switch to the **refine** workflow in a fresh chat. Do not rewrite the issue body while within this workflow.
5. **Commit** and **push** fixes on the **same feature branch** as the implementation under test until UAT is complete. Remind the user that you are waiting for them to confirm when the merge is done before performing final cleanup and switching back to the main branch.
6. When the user **explicitly says** the PR is **merged** (or integration to the default branch is complete **on their side**): **check out** the default branch, **pull** latest, and treat the workspace as ready for the next piece of work. This step is **not** “the assistant merges the PR”; it is **sync local git after the human merged**. The feature branch will be deleted remotely when the branch is merged. Ensure that the same thing happens on the local repo.

## Notes

- UAT is not the place to silently broaden scope; capture product decisions in comments or run **refine.md** when the specification must change.
- If a gap is purely operational (data, config), document it in comments and fix procedures or README as appropriate without changing the issue’s acceptance story unless the user asks.
- The user may initiate this workflow with just `!wk-ship #<number>` (see **STYLE.md**). This does not signal anything more than they are about to start performing UAT.
- Work on one issue at a time and review the solution with the user before implementing it.
- Design and implement tests before implementing to solution to any reported issues.
- Commit any unsaved prior work before starting work on a new issue.
- Acceptance test is generally run against the local dev instance, running locally in the current workspace.
- If the required work appears very large, suggest a proposed breakdown of the work into more manageable child tickets in the chat. **Do not create child tickets** unless and until the user agrees. As a guideline, a ticket should be considered too large if it appears likely to consume more than 150k of context during implementation, including automated test runs but not user driven UAT.
- Prior to merge and after any code changes have been made, all tests must have been run. This includes front-end, back-end, integration and any other automated tests that exist for this project. If any code changes have been made after any tests have been run, you need to re-run those tests to ensure that all tests have been run after any and all code changes before we are ready to merge. For the purposes of this point, any change to a file other than a markdown (*.md) file is considered a code change. Include test execution time as well as total number of tests passed in the PR body, if available.

