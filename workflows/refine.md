# Requirements refinement workflow

Use this workflow when turning a **feature** GitHub issue into a single, agreed requirements document on GitHub. It is **agent-agnostic** plain Markdown. System boundaries and subsystem map live in **[ARCH.md](../ARCH.md)**; coding, testing, and delivery expectations live in **[STYLE.md](../STYLE.md)**—follow those files rather than duplicating them here.

## Pre-requisites

- A **fresh chat** dedicated to this refinement (do not reuse a thread that mixed another ticket’s implementation or UAT).
- The target issue **number** `N` and repository context (owner/repo or equivalent).
- **GitHub access** via `**user-github` MCP**. If github MCP is unavailable or fails, abort and report the problem to the user.
- If the issue is **not** assigned to the current user, assign the issue to the current user.
- The issue must be **open**; if it is closed or marked duplicate, confirm with the user before proceeding.
- The issue should not be labelled as READY. If it is, confirm with the user whether re-refinement is really necessary.

## Steps

1. **Classify** the issue: this workflow targets **features**, not bugs. If the issue reads as a defect report or is misclassified, call that out and agree with the user whether to treat it as refinement (possibly after re-scoping) or hand off to another process before rewriting scope.
2. **Read** the issue (title, body, labels, and relevant comments) from GitHub.
3. **Draft** a fully detailed story: user voice, context, explicit **out of scope**, **acceptance criteria**, and risks/limitations/caveats. Ground it in **[ARCH.md](../ARCH.md)** and **[STYLE.md](../STYLE.md)** only by reference—do not paste long policy.
4. **Discuss gaps** with the user; revise the draft until the user agrees the requirements are complete. Put the draft requirements in the issue body, not in the chat. Discussion points can go in the chat, but I want to see the draft requirements on the issue on github.
5. **Update the issue body** on GitHub with the agreed text so the issue remains the **single source of truth** (for example `issue_write` with `method: update` and the new `body`).
6. When the user agrees that the issue details are complete and not before, label the issue as READY and inform the user that this workflow is complete.

## Notes

- Refinement ends with the **issue body** updated; long procedural detail stays in this file and in **STYLE.md** / **ARCH.md**, not duplicated across every comment.
- If requirements change materially later, either run this workflow again or treat the change as implementation detail per **implement.md**, as the team prefers.
- The github issue should not be labelled READY unless and until the user has explicitly agreed that the requirements are correct and complete and we're ready to finish off this workflow.
- Build the detailed requirements on the issue description. It's easier for the user to read and review it there than in the chat.
- Don't assume we're ready just because the user has given you some feedback. Wait for explicit agreement from the user that the ticket is ready or the refinement is complete or it's time to finish the workflow.
- If the required work appears very large, suggest a proposed breakdown of the work into more manageable child tickets in the chat. **Do not create child tickets** unless and until the user agrees. As a guideline, a ticket should be considered too large if it appears likely to consume more than 150k of context during implementation, including automated test runs but not user driven UAT.
- As you update the issue body in github, maintain a copy in a local markdown file and update it between successive updates during refinement. The local difference tracking features help the user understand what sections have been added/changed/removed in each iteration.

