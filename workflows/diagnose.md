# Bug diagnosis workflow

Use this workflow when starting work on a **bug**, **defect**, **regression**, or **maintenance** issue (for example failing tests, incorrect behaviour, or an incident reduced to a tracked issue). It produces a **recorded diagnosis** on GitHub before substantive code changes. It is **agent-agnostic** plain Markdown. Trust boundaries live in **[ARCH.md](../ARCH.md)**; coding and testing expectations live in **[STYLE.md](../STYLE.md)**—follow those files rather than duplicating them here.

## Relationship to other workflows

- **refine.md** targets **features** and ends with agreed requirements in the issue body (and, when used, a READY label). **diagnose.md** targets **defects** and ends with **documented findings** and a **READY** label. Findings are documented on the issue as comments - not a product-requirements rewrite.
- **implement.md** follows when the user is ready to **plan and ship** a fix; the explicit **plan approval** step in **implement.md** still applies before application code changes.

## Pre-requisites

- A **fresh chat** dedicated to this diagnosis (do not reuse a thread that mixed another ticket’s implementation or unrelated work).
- The target issue **number** `N` and repository context (owner/repo or equivalent).
- **GitHub access** via `**user-github` MCP**. If GitHub MCP is unavailable or fails, abort and report the problem to the user.
- If the issue is **not** assigned to the current user, assign the issue to the current user.
- The issue must be **open**; if it is closed or marked duplicate, confirm with the user before proceeding.
- The issue should **not** already be labelled **READY**. If it is, confirm with the user before proceeding.

## Steps

1. **Classify** the issue: this workflow targets **bugs and defect/maintenance work**, not greenfield **features**. If the issue reads as an underspecified feature request, call that out and agree with the user whether to switch to **refine.md**, narrow the bug report first, or proceed.
2. **Read** the issue (title, body, labels, and relevant comments) from GitHub.
3. **Characterise** the problem in concrete terms: **symptom**, **expected behaviour**, **actual behaviour**, and **impact** (who or what is affected). Use any acceptance criteria or “done” language already on the issue when present.
4. **Investigate** enough to support the ticket: reproduce locally when feasible (commands, environment, fixture data), and gather **evidence** (failing test names and output, logs, stack traces, bisection or regression range). Separate **confirmed facts** from **suspected** causes. For **failing tests**, note whether the failure looks like **test drift** (obsolete assertion or harness) versus **product regression** (behaviour wrong under the test’s intent).
5. **Ground** the analysis in **[ARCH.md](../ARCH.md)** when the failure crosses trust boundaries or subsystem boundaries; cite it by reference only.
6. **Discuss** open questions with the user (environment parity, intermittent reproduction, product intent). Adjust the write-up until the user agrees the diagnosis is **accurate and complete enough** to plan a fix.
7. **Document** the agreed findings on the GitHub issue—typically a **single consolidated comment** (for example `**add_issue_comment`**) with clear sections, such as:
  - **Summary** — Short overview for someone scanning the thread.
  - **Reproduction** — Steps or commands; state explicitly if not reproduced locally.
  - **Evidence** — Failing tests, traces, commit or code pointers.
  - **Root cause** — What broke and why; label **Confirmed** vs **Suspected** honestly.
  - **Suggested fix direction** — High level only; detailed plan belongs in **implement.md**.
  - **Out of scope / follow-ups** — Deliberate exclusions or separate issues.
   If the issue body is vague or misleading and the user wants it corrected, coordinate **issue_write** with the user so the issue stays readable; otherwise prefer **comments** so the original report and the diagnosis remain distinguishable in history.
8. Inform the user that **diagnosis for #N is complete** and label the issue as **READY** and to advance to the **implement** workflow when they are ready.

## Notes

- Diagnosis ends with **documentation on the issue**, not merged code. While inside this workflow, avoid large product changes unless the user explicitly directs otherwise (tiny reproducibility spikes may still be discussed case by case).
- If investigation shows the report is invalid, duplicate, or not reproducible, say so in the comment and agree with the user whether to close or retarget the issue.

