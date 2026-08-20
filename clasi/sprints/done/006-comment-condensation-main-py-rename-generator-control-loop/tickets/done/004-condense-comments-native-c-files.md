---
id: '004'
title: 'Condense comments: native/ C++ files'
status: done
use-cases:
- UC-001
depends-on: []
github-issue: ''
issue: condense-comments-across-the-codebase.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Condense comments: native/ C++ files

## Description

Every file under `native/`: `moddiffdrive.cpp` (24%, 117/332),
`moddiffdrive_glue.c`, `platform_ports.{h,cpp}`, `watchdog.{h,cpp}`,
`i2c_broker.{h,cpp}`, `modwifiuart.cpp`, `modwifiuart_glue.c`,
`wifi_uart_fwd.h` (68%, 72/20 — the single worst-ratio file in the
repo), `nezha_leaf.h`, `nezha_wire.h`, `codal_fwd.h`, `native/hal/*.h`
(42–73% per the issue), `native/codal_app/*`. No overlap with `src/`
or `tests/`, so no dependency on other comment-condensation tickets —
but **this ticket must land before ticket 006** (the native binding
additions for step-driven mode), which edits `moddiffdrive.cpp`,
`moddiffdrive_glue.c`, and `platform_ports.{h,cpp}` — landing
condensation first means ticket 006 edits already-condensed files
instead of a large diff fighting an in-flight condensation pass.

Apply the same condensation discipline as ticket 002 (narrative
history and provenance prose out; short docstrings, trimmed
function-level comments, and landmine markers in), with the C/C++
addition from `CLAUDE.md`'s style rule: **keep units in `// [unit]`
trailing comments** — these are exactly the "non-obvious constraint"
kind of comment this sweep is meant to preserve, not cut.
`native/watchdog.h`'s safety-invariant comments (the "must never
yield, sleep, or fiber-switch" block) and
`native/platform_ports.h`'s port-boundary comments are landmine
markers — keep them, tightened if verbose, not deleted.

**Comments-only. No behavior change.** No `.cpp`/`.h`/`.c` line other
than a comment or a blank line inside a comment block may change.

## Acceptance Criteria

- [x] Every file under `native/` keeps: a short file-purpose comment
      at the top; trimmed function-level comments (purpose,
      parameters, units); every `// [unit]` trailing comment
      (CLAUDE.md style, load-bearing); every landmine/safety-invariant
      marker (e.g. `watchdog.h`'s never-yield invariant,
      `platform_ports.h`'s fiber-only-caller boundary note).
- [x] Narrative history and provenance prose reduced to one-line
      pointers or removed.
- [x] No non-comment line changes in any `native/` file (verify via
      diff review — a build is not required to confirm this, since no
      token outside a comment changes).
- [x] `uv run pytest` stays green at the 223-passed / 518-subtests
      baseline, unchanged (native/ has no direct Python test coverage,
      but nothing here should affect the Python-side suite at all —
      confirms no accidental non-comment edit).
- [x] If a build is run as a spot-check (`./build.sh --clean
      --with-diffdrive`), it still links clean with the pre-existing
      method table (no `step`/mode-latch symbols yet — those are
      ticket 006's addition, not this ticket's). NOT RUN this ticket
      per the dispatch instructions (comment-only C++ change; no
      firmware build required for this ticket's gate). Zero-behavior-
      change instead verified mechanically: a preprocessor-free
      comment-stripping tokenizer diffed the pre- and post-edit token
      stream of every changed file and found them byte-identical (see
      ticket completion notes / commit message for method).

## Testing

- **Existing tests to run**: `uv run pytest` (223 passed / 518
  subtests baseline) — confirms no accidental behavior change reached
  the Python side. A build (`./build.sh --clean --with-diffdrive`) is
  a reasonable spot-check but not required to pass this ticket's own
  gate, since comment-only C/C++ changes cannot affect the produced
  binary's behavior — only its debug-info size, if any.
- **New tests to write**: none — comments-only.
- **Verification command**: `uv run pytest`
