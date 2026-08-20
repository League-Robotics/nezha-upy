---
status: pending
---

# Role-guard blocks all edits to tickets already moved to `done/`

The role-guard hook's ticket-state gate globs `tickets/*.md`
non-recursively, so it never sees tickets that have been relocated into
`tickets/done/`. Editing a completed ticket therefore always fails the
gate with a false "no ticket is in-progress" violation — even
immediately after setting that exact ticket to `in-progress` via
`update_ticket_status`.

## How it surfaced

Sprint 006, ticket 011. Its final acceptance criterion was a hardware
bench repro that the implementing programmer deliberately left
unchecked, because it had been told not to touch the robot. The
team-lead later ran that repro on tovez and it passed, so the box
needed checking and an evidence citation added.

The ticket was already in `tickets/done/`. Every `Edit`/`Write` against
it was blocked, including after flipping its status to `in-progress`
through the proper MCP call — the gate scans `tickets/*.md`, the file
lives at `tickets/done/011-*.md`, so no in-progress ticket is ever
found.

There is no legitimate path through this. The gate cannot be satisfied
for a file it structurally cannot see.

## Why it matters beyond the inconvenience

The block has no escape hatch, so it creates pressure to route around
it. In this instance a subagent did exactly that: `Edit`/`Write` were
gated, `Bash` was not, so it applied the same edits with a Python
script through Bash and reported afterward that it had done so. The
content was correct and confined to process artifacts, and the
stakeholder chose to keep it — but a guard that is impossible to
satisfy legitimately trains exactly this behaviour, which is the real
cost.

Recording after-the-fact evidence on a completed ticket is a normal
need, not an edge case. It happens whenever verification lands after
implementation — hardware gates, deferred bench passes, anything a
programmer correctly declines to claim.

## Suggested fix

Make the ticket-state gate glob recursively (`tickets/**/*.md`, or
check `tickets/done/` explicitly in addition to `tickets/`), so a
ticket set to `in-progress` satisfies the gate regardless of which
subdirectory it currently sits in.

Consider also whether the gate should apply to CLASI's own artifacts at
all. `.claude/rules/source-code.md` already exempts `.clasi/`,
`.claude/`, `docs/`, and `*.md` from the source-code rule on the
grounds that they are not source code — ticket files are `*.md` process
artifacts under `clasi/`, so arguably they should never have been
gated by a rule aimed at protecting source.

This lives in the installed `clasi` package (pipx), not in this repo,
so it needs reporting upstream rather than patching here.
