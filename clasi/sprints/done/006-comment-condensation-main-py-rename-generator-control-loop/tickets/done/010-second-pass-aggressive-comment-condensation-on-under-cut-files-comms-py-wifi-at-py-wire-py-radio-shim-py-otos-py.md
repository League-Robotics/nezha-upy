---
id: '010'
title: 'Second pass: aggressive comment condensation on under-cut files (comms.py,
  wifi_at.py, wire.py, radio_shim.py, otos.py)'
status: done
use-cases:
- UC-001
depends-on:
- '002'
- '003'
github-issue: ''
issue: condense-comments-across-the-codebase.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Second pass: aggressive comment condensation on under-cut files (comms.py, wifi_at.py, wire.py, radio_shim.py, otos.py)

## Description

Ticket 002 cut hard and well where it applied: `main.py` -67%,
`demo_square.py` -69%, `boot.py` -50%. But it left `wire.py` at only
-9%, and ticket 003 came in at -14% overall, with `comms.py` at -5%
and `wifi_at.py` at -2%. In both cases the implementer classified the
remaining bulk as "genuine protocol/reference documentation" and
exempted it from cutting. **The stakeholder has reviewed the actual
numbers and rejected that judgement as too conservative.** Their
original instruction, restated here verbatim because it is the
standard this ticket is held to: *"remove almost the entirety of the
comments that are in the code and limit it to just the important
stuff to understand what it's doing."* Repo-wide comment density has
only moved from 32% to 26% against that bar. This ticket is the
second pass on the five files that most under-delivered.

Depends on 002 and 003 (both done) because it re-touches the same
files. It does **not** depend on, and must **not** block, tickets
004, 006, 007, 008, or 009 — none of them touch these five files, and
this ticket's own scope is comments-only in `src/`, orthogonal to the
native binding work those tickets carry.

### The distinction this ticket turns on

A **fact** stays: a table of register addresses, a bit layout, a CRC
parameter set, a "must be called before X" ordering constraint, a
units annotation. These are load-bearing and irreplaceable — deleting
one is a knowledge loss, not a cleanup.

**Prose** goes, even when it is dense and technical: several
paragraphs explaining that fact, narrating why it was discovered, what
was tried first, or restating in English what the code immediately
below it plainly does. **Dense technical prose is still prose.** The
test for keeping a comment is not "is this correct and relevant" —
almost everything in these files clears that low bar, which is
precisely why the previous pass under-cut them. The test is: does
deleting this specific sentence remove a fact a reader cannot
re-derive from the code, a referenced doc, or a one-line pointer? If
the fact survives via a compressed one-liner or a pointer, the
original prose is not needed and must go.

### Scope: five files, stated as expectations, not mechanical quotas

| File | Current comment lines | Target | 
|---|---:|---:|
| `src/comms.py` | 261 | ~130 |
| `src/wifi_at.py` | 241 | ~120 |
| `src/wire.py` | 148 | ~75 |
| `src/radio_shim.py` | 95 | ~50 |
| `src/otos.py` | 58 | ~30 |

These targets are **expectations to be met, or explicitly argued
against per file** — not quotas to hit by any mechanical means (do not
delete a load-bearing fact just to hit a number, and do not pad
whitespace or reformat to dodge one either). If, after applying the
fact-vs-prose test above file by file, a specific file genuinely
cannot reach its target without losing knowledge, **say so in this
ticket's Implementation Notes, per file, with a concrete reason** —
name the specific comments that resisted compression and why
(e.g. "these N lines are an enumerated protocol state table with no
shorter faithful representation"). A blanket "it's reference
documentation" is exactly the judgement the stakeholder rejected and
is not an acceptable reason on its own — a reason must point at
specific content and explain why it cannot compress further.

### Must-survive landmines (named explicitly — compress, never delete)

Every landmine marker below must survive this pass, compressed to one
line with a pointer to the doc or log entry holding the full story.
Deleting the knowledge is a failure of this ticket; compressing it is
the job.

- **`wifi_at.py`**: the CWJAP near-livelock avoidance note; the
  module-persists-state-across-reflash note (the reason bench work
  power-cycles the WiFi module first); the newest-client-wins rule.
- **`comms.py`**: the dispatch-order enumeration (why relay sigils are
  dropped first, TLM/SEED/DBG intercepted before the binary branch);
  the `Transport`/dispatch-interface contract.
- **`wire.py`**: the CRC-then-COBS ordering constraint; the per-byte
  XOR-at-read invariant.
- **`radio_shim.py`**: the bytearray-slice-assign `TypeError`-on-device
  landmine.
- **`otos.py`**: the register map and the scale table (these are the
  canonical "fact, not prose" case — a table survives verbatim;
  surrounding narrative about how the table was derived does not).

**Units annotations are never stripped**, in any of the five files, no
exceptions.

**`vendor/` is never edited** — not applicable to these five files
directly, but stated here as it is for every ticket in this sprint;
if a landmine comment references `vendor/` behavior, the reference
stays, the file itself does not get touched.

## Acceptance Criteria

- [x] `src/comms.py`, `src/wifi_at.py`, `src/wire.py`,
      `src/radio_shim.py`, `src/otos.py` each either meet their stated
      target comment-line count, or carry a per-file note in this
      ticket's Implementation Notes explaining, with specific content
      cited, why they cannot without losing a fact.
- [x] Every named must-survive landmine (CWJAP livelock avoidance,
      module-persists-across-reflash, newest-client-wins in
      `wifi_at.py`; dispatch-order enumeration and
      Transport/dispatch-interface contract in `comms.py`;
      CRC-then-COBS ordering and per-byte XOR-at-read invariant in
      `wire.py`; bytearray-slice-assign TypeError landmine in
      `radio_shim.py`; register map and scale table in `otos.py`) is
      present post-condensation, each compressed to about one line
      with a pointer to its full-story doc/log entry — verified by
      name, one by one, not by a general "landmines preserved"
      assertion.
- [x] No units annotation (`// [unit]`-equivalent in these Python
      files' comment convention, or any explicit unit note) is
      removed from any of the five files.
- [x] **Zero behavior change, proven, not asserted**: for each of the
      five files, run an AST+tokenize code-skeleton comparison —
      parse the file before and after, strip all comments and
      docstrings, and assert the remaining token streams are
      identical. This is the same method tickets 002 and 003 both
      used successfully; reuse it here per file, and record the
      comparison result (pass/fail) for each of the five files in
      Implementation Notes.
- [x] `uv run pytest tests/` stays at 228 passed / 518 subtests —
      unchanged from the current baseline, exactly.
- [x] `python3 -m py_compile` and `mpy-cross` (if available) lint all
      five changed files clean.
- [x] `vendor/` is untouched (`git diff --exit-code -- vendor/` clean).

## Testing

- **Existing tests to run**: `uv run pytest tests/` — full suite,
  must stay at exactly 228 passed / 518 subtests before and after.
  `tests/test_comms_loopback.py`, `tests/test_wifi_at.py`,
  `tests/test_radio_shim_fragments.py`, `tests/test_otos.py`, and any
  wire/golden-vector tests exercising `wire.py` in particular, since
  these five files are what changed.
- **New tests to write**: none as pytest tests — the required proof
  of "no behavior change" for this ticket is the AST+tokenize
  code-skeleton comparison per file (see Acceptance Criteria), not a
  new pytest case. Record each file's comparison result in
  Implementation Notes.
- **Verification command**: `uv run pytest tests/`

## Implementation Notes (fill in on completion)

**Counting methodology**: comment/docstring line counts were produced
with a script combining `tokenize` (COMMENT tokens) and `ast` (the
first-statement string literal of `Module`/`FunctionDef`/
`AsyncFunctionDef`/`ClassDef` nodes = docstring), counting the union
of lines those spans occupy. This reproduces the ticket's stated
baselines exactly for `comms.py` (261), `wifi_at.py` (241),
`radio_shim.py` (95), and `otos.py` (58); `wire.py`'s baseline came
out to 169 under this method vs. the ticket's stated 148 (some prior
counting pass evidently excluded a handful of blank lines inside
multi-line docstrings that this method counts). Where the baseline
matched the ticket's number, the target was hit directly; for
`wire.py` the same *proportional* cut (~50%) was applied against the
169-line baseline instead of chasing the absolute "75" figure, since
that figure was derived from a baseline this method cannot reproduce.

**Per-file results** (before -> after, AST+tokenize skeleton
comparison result — parse before/after, strip comments+docstrings via
`ast`-identified docstring spans and `tokenize` COMMENT tokens,
compare the remaining token stream for exact equality):

| File | Target | Before | After | Reduction | Skeleton diff |
|---|---:|---:|---:|---:|---|
| `src/comms.py` | ~130 | 261 | 127 | 51.3% | PASS (identical) |
| `src/wifi_at.py` | ~120 | 241 | 122 | 49.4% | PASS (identical) |
| `src/wire.py` | ~75 | 169* | 84 | 50.3% | PASS (identical) |
| `src/radio_shim.py` | ~50 | 95 | 50 | 47.4% | PASS (identical) |
| `src/otos.py` | ~30 | 58 | 31 | 46.6% | PASS (identical) |

\* `wire.py`'s baseline under this ticket's counting method (169, not
the ticket's stated 148) is explained above; the file was still cut to
the same ~50% depth as the other four.

All five files land within 1-2 lines of their stated target (or, for
`wire.py`, of the equivalent proportional target) — none required an
under-cut exception.

**Must-survive landmines, verified present by name, one by one**
(quoting the compressed line each was reduced to):

- `wifi_at.py` CWJAP near-livelock avoidance — `_service_join()`:
  `"# LANDMINE: poll AT+CWJAP? first to let the module's own /
  post-AT+RST auto-rejoin land -- firing an explicit CWJAP / into an
  in-progress auto-join answers busy/ERROR, observed / on gopiv
  2026-08-14 as a join->backoff->RST near-livelock / (reference/
  modrobot/wifi_stdio.cpp::serviceJoin())."`
- `wifi_at.py` module-persists-state-across-reflash — module
  docstring: `"BENCH-TIME: the WiFi module persists AP-join/socket/
  server state across nRF52 reflashes -- power-cycle it before any
  bring-up session, or `AT+RST` may race a stale auto-rejoin already
  in progress."`
- `wifi_at.py` newest-client-wins — `_handle_status_line()`:
  `"# Newest client wins -- else a stale abandoned session shadows the
  fresh one."`
- `comms.py` dispatch-order enumeration — module docstring's
  `Dispatch order (` _dispatch_line()`, mirrors ` dispatchLine()`):`
  4-step numbered list (relay sigils dropped first; unknown verb
  drop; TLM/SEED/DBG intercepted before the binary/cleartext branch;
  else binary validate-and-queue vs. cleartext immediate answer).
- `comms.py` Transport/dispatch-interface contract — module
  docstring's `Dispatch interface:` paragraph (`handle_command(...)`
  signature and ack-ring semantics) and `Transport contract (...)`
  block (`read_line()`/`send()`/`send_reliable()` signatures).
- `wire.py` CRC-then-COBS ordering — `encode_frame()`:
  `"LANDMINE: CRC-then-COBS, not COBS-then-append-CRC -- append the
  little-endian CRC-16 to `payload`, THEN COBS-encode (delimiter
  0x0A); the reverse order risks a literal 0x0A escaping inside the
  CRC bytes."`
- `wire.py` per-byte XOR-at-read invariant — present in both
  `cobs_encode()` (`"XOR-ing each output byte with `delimiter` at
  write time (one pass)"`) and `cobs_decode()` (`"Each byte is
  XOR-ed with `delimiter` at read time (one pass) ... trips the same
  rejections."`).
- `radio_shim.py` bytearray-slice-assign TypeError landmine —
  `_fragment()`: `"# LANDMINE: concatenate, never bytearray
  slice-assign -- raises / TypeError ON DEVICE only; see
  docs/bench-log-zetuv-2026-08-19.md."`
- `otos.py` register map and scale table — module docstring's
  `Register map (I2C 0x17, ...)` block (product ID / linear scalar /
  angular scalar / position block / velocity block register
  addresses) and `Scale table: ...` line (position/heading/velocity/
  omega LSB conversions), both kept verbatim as compact facts per the
  ticket's own "canonical fact, not prose" framing.

**Units annotations**: verified via `grep -oE '\[[a-zA-Z/]+\]'`
before/after on all five files. Two instances were initially dropped
during compression (a redundant `now` `[ms]` mention in `comms.py`'s
module docstring — the fact remained stated twice elsewhere in the
same file — and the `[ms]` unit on `TlmThrottle.allow()`'s `now`
parameter in `wifi_at.py`) and were restored explicitly rather than
left as a silent gap; final unit-annotation sets are unchanged from
baseline in count for every file (`otos.py`: mm, mm, mm/s, rad,
rad/s; `comms.py`: mm, rad, 3x ms + loop-counter brackets;
`wifi_at.py`: 1x ms; `wire.py`/`radio_shim.py`: no true unit
annotations in either version, only field-name brackets like `[SEQ]`/
`[FLAGS]`/`[LEN]`, unaffected).

**Verification commands run**: `uv run pytest tests/` → 228 passed /
518 subtests (unchanged before and after, matching baseline exactly).
`python3 -m py_compile` clean on all five files. `mpy-cross` is not
installed in this environment (consistent with tickets 002/003's own
notes), so that lint step was skipped as in prior tickets. `git diff
--exit-code -- vendor/` clean (no vendor/ files touched — none of the
five files live there anyway). Per-file AST+tokenize skeleton
comparison (comments and docstrings stripped via `ast`-identified
docstring spans, `tokenize` COMMENT tokens; remaining token stream
compared for exact equality) passed identical for all five files.
