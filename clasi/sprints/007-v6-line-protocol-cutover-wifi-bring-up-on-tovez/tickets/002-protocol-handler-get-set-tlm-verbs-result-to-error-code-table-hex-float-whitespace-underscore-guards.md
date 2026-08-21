---
id: '002'
title: 'Protocol handler: GET/SET/TLM verbs, Result-to-error-code table, hex-float/whitespace/underscore
  guards'
status: done
use-cases:
- SUC-003
- SUC-004
- SUC-005
depends-on:
- '001'
github-issue: ''
issue: port-v6-line-protocol-hard-cutover-from-v5.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Protocol handler: GET/SET/TLM verbs, Result-to-error-code table, hex-float/whitespace/underscore guards

## Description

Extend `src/core/protocol.py` (ticket 001) with `GET`, `SET`, and
`TLM`, and the `Result` → wire-error-code mapping every verb's
rejection path uses (`protocol.md` §4/§6.1):

| code | name | meaning |
|---|---|---|
| 1 | `ERR_UNKNOWN` | no such verb or field name |
| 2 | `ERR_BADARG` | malformed/non-finite argument, wrong arity |
| 3 | `ERR_RANGE` | declared bound violated |
| 4 | `ERR_FULL` | queue full |
| 6 | `ERR_UNIMPLEMENTED` | recognized, not wired on this build |
| 8 | `ERR_NOT_CONFIGURED` | refused pre-ready |
| 10 | `ERR_BUSY` | subsystem in motion |
| 11 | `ERR_DUPLICATE_ID` | reused id |

`GET [name]` → `get name value` (one field) or one `get` line per
field for bare `GET` (adapter-driven — the handler holds no field
table itself, per §7); unknown name → silent, no reply, NOT malformed
(distinct from every other unknown-token case in this grammar — worth
its own test). `SET name value [#id]` → `ok [#id]` / `err [#id]
<code>`. `TLM mode` → no reply; `mode` decodes
`OFF`/`POSE`/`FULL`/`NOW`/`AUTO`/`BUFFER`, persisted via the adapter's
`onTlm`.

Port-specific decisions this ticket must pin with tests
(`protocol.md` §9.4, issue items 2–3):

- Python's `int()`/`float()` strip leading/trailing whitespace AND
  accept `_` digit separators — the wire grammar admits neither for a
  field value. Guard explicitly (reject `SET x 1_000`/`SET x " 5"` as
  `ERR_BADARG`, even though bare Python parsing would accept them).
  Note the tokenizer already collapses space runs before a field
  pointer is ever produced, so a literal leading space can't reach
  the decoder at all — the guard's real job is `_` and any embedded
  tab/`\v`/`\f`/`\r`, which the field grammar's own `any bytes except
  ' ' and '\n'` still legally admits as field bytes.
- Hex-float rejection: confirm `float("0x1.8p3")` already raises
  `ValueError` in CPython/MicroPython (issue text says no action
  needed) — pin it with an explicit test so this can never silently
  regress if the parsing helper changes later.

## Acceptance Criteria

- [x] `GET`/`SET`/`TLM` implemented in `protocol.py`, dispatched
      through the same tokenizer/dispatch core from ticket 001.
- [x] `Result` → error-code table complete (all 8 codes), with a
      `resultCode()`-equivalent helper tested against every code.
- [x] Golden-vector harness green for every `GET`/`SET`/`TLM` vector,
      including bare `GET` (multi-line reply) and unknown-name-silent.
- [x] Explicit tests: `SET` rejects an underscore-separated numeric
      field; `SET` rejects a tab/`\v`/`\f`/`\r`-containing field
      (still legal per the field grammar's byte class, but the
      leading-space case is already closed by the tokenizer — the
      test should say which case it's actually covering); hex-float
      literal rejected by the numeric parser (pinned, not just
      assumed).
- [x] `py_compile` clean; no MicroPython-incompatible syntax.

## Testing

- **Existing tests to run**: `python3 -m pytest tests/`
  (ticket 001's harness + suite, confirm no regression).
- **New tests to write**: golden-vector cases for GET/SET/TLM;
  underscore/whitespace-leniency guard tests; hex-float pin test;
  unknown-GET-name-is-silent-not-malformed test.
- **Verification command**: `python3 -m pytest tests/`

## Implementation Plan

**Approach**: Extend the dispatch table from ticket 001 rather than
branching around it. Implement the numeric-field parser (shared by
`SET`'s value and any future numeric field) with the whitespace/
underscore guards built in from the start, so ticket 003's `WHEELS`
reuses the same parser instead of a second one that might diverge.

**Files to modify**:
- `src/core/protocol.py` — add `GET`/`SET`/`TLM` handlers, the
  `Result` table, the guarded numeric-field parser.
- `tests/unit/test_protocol_golden_vectors.py` (or wherever ticket
  001 put it) — extend with this ticket's vectors/cases.

**Testing plan**: see Acceptance Criteria / Testing above.

**Documentation updates**: none this ticket.
