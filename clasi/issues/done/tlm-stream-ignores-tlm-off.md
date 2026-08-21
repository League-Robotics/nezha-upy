---
status: done
---

# Telemetry stream ignores `TLM:OFF` and floods the USB serial link

A robot running the current MicroPython image streams `TLM:0:0:0`
continuously out the USB serial port and does not stop when commanded
`TLM:OFF`. The flood makes the board effectively unreachable over
`mpremote`.

## Evidence (measured on the bench, 2026-08-20)

Board on `/dev/cu.usbmodem2121402`, self-identifying as
`ID:diffdrive:tovez:1.0.0`:

- Passive read: 108 identical `TLM:0:0:0` lines in 6 s — ~19 Hz,
  ~180 B/s, one distinct line, no banner.
- `TLM:OFF` sent: **58 TLM lines in 3 s before, 58 after.** No change.
- The board is demonstrably listening the whole time — in the same
  session `PING` returned `PONG:t=53948`, `ID` returned
  `ID:diffdrive:tovez:1.0.0`, and `VER` returned `VER:1.0.0`.
- `STATUS` returned nothing parseable, which may be a second symptom
  (its reply is likely being lost in the flood).

So the verb is accepted but has no effect on the emitter.

## Why this looks like a defect, not configuration

`src/telemetry.py:98` initialises `self.mode = 0` — telemetry off by
default. `src/comms.py` defines the mode values (`TLM_MODE_OFF/AUTO/ON`)
and parses `TLM:` arguments case-insensitively against
`NOW/ON/AUTO/OFF`. Nothing in that path should produce an unconditional
stream, so some emitter is running without consulting
`Comms.telemetry.mode`.

Note the observed line has **three** fields (`TLM:0:0:0`), which matches
neither `src/telemetry.py`'s 22-field frame nor the binary reply
envelope. Finding what formats that specific 3-field line is probably
the fastest route to the emitter — a repo-wide grep for a literal
`"TLM:"` format string finds hits only in `tests/` and
`reference/modrobot/`, so it is likely built by concatenation.

## Impact

- `mpremote` cannot complete its REPL handshake through the flood and
  reports the misleading error "failed to access ... (it may be in use
  by another program)", which reads as a port conflict or a cable fault
  and sends debugging in the wrong direction. This cost real bench time.
- Any tooling that identifies a board by talking to it has to fight the
  stream.

## Acceptance

- `TLM:OFF` silences the stream; `TLM:ON`/`TLM:AUTO` restore it.
- With telemetry off, `mpremote connect <port> exec "print(1)"`
  succeeds against a booted robot.
- A regression test covers "mode off means no emission" at the
  comms/telemetry seam (offline, no hardware).

Related: [[robot-identity-collision-and-stale-device-map]] — both were
found in the same bench session, and the flood is what blocked
identifying the board by name.

---

## Resolution — misattributed. The emitter is not this firmware.

### The board was the vevov spike, not a fleet robot

The flooding board self-identified as `ID:diffdrive:tovez:1.0.0` over
the **v5 cleartext protocol**. This repo does not implement that
surface. Grep-verified across the whole repo (excluding `vendor/`):
no `TLM:` format string and no `diffdrive:` identity string exists in
any source file — the only hits are `tests/`, `docs/`, and these issue
files.

`reference/vevov-micropython-spike-handoff.md` does implement it:

> line 8:   DAPLink UID: `9906360200052820b8e12372c44f4f67...`
> line 418: `PING  -> PONG   # cleartext verbs + binary TLM: push frames`

That UID is **exactly** the board this issue's sibling
([[robot-identity-collision-and-stale-device-map]]) tabulates as
announcing `ID:diffdrive:tovez:1.0.0`. The spike is a deliberately
retained reference artifact running a different codebase with a
different protocol. Its telemetry does not consult
`Comms.telemetry.mode` because it has no `Comms.telemetry`.

So the issue's central inference — "some emitter is running without
consulting `Comms.telemetry.mode`" — sent debugging into
`src/core/telemetry.py`, which was never involved.

### The 2026-08-19 zetuv flood has a mechanism, now nameable

That one (bench log §12) was a different board and was left
"origin **not identified**". The facts recorded there were: survived
Ctrl-C, survived a probe-level `pyocd reset`, reappeared fresh on every
boot, and was cleared by re-deploying the **unchanged** hex — which hit
a locked device and triggered `mbdeploy`'s CTRL-AP **mass erase**.

Work done since names a mechanism that fits every one of those:
`mp_main()` probes the **filesystem** for `main.py` and runs it, ahead
of anything frozen. The FS region (`0x6d000..0x73000`) lies outside the
hex, so an ordinary `--hex` deploy leaves it intact and a probe reset
does not touch flash at all — but a mass erase wipes it. A stale
`main.py` from another project would therefore survive everything that
failed and die to the one thing that worked.

Not proven: that board is not currently on the bench, and the mass
erase destroyed the evidence. Recorded as the leading hypothesis with
its supporting mechanism, not as a finding. `mpremote fs ls` now
answers it in seconds if it recurs — it did not exist as a usable check
before filesystem deployment was built.

Checked on the one robot that IS connected (tovez,
`...a8fdb5e413abb276`): FS holds `robot.json`, `main.mpy`,
`demo_square.mpy`, `demo_util.mpy`, `tour_state.csv` — exactly the
deploy set, nothing foreign.

### What was actually fixed

The third acceptance criterion was a real coverage hole, independent of
the misattribution, so it was closed properly.

`tests/test_comms_loopback.py` split cleanly in two: verb tests assert
`TLM:OFF` sets `telemetry.mode`, and policy tests drive
`TelemetryPolicy` directly. **Nothing joined the halves** — an emitter
that set the flag and then ignored it passed the entire suite. That is
precisely the reported symptom's shape.

Four seam tests added, driving the verb over the loopback wire and then
pumping the emitter:

- `test_tlm_off_over_the_wire_silences_a_moving_robot` — sends
  `TLM:OFF` to an actively-moving robot, then emits across 2.8 s (past
  both the 25 ms floor and `COAST_HOLDOFF_MS`): zero frames.
- `test_tlm_on_over_the_wire_restores_the_stream_while_parked`
- `test_tlm_off_then_auto_resumes_only_when_moving`
- `test_tlm_off_still_delivers_pending_acks` — pins the **deliberate**
  exception: OFF suppresses unsolicited frames, but an ack is a reply.
  A host sends `TLM:OFF` precisely when it wants to talk to the board;
  dropping acks there would hang it.

**Mutation-verified.** Flipping the gate to `unsolicited = True` under
`TLM_MODE_OFF` — the exact reported behaviour — fails three of the four
new tests. The pre-existing `test_tlm_on_off_auto_reply_with_status`
stays **green** under that same mutant, which is the direct measurement
of the hole.

The first two acceptance criteria are not verifiable here: they
describe a board running other firmware.

Also rewrote the "Known defect" note in
`docs/bench-acceptance-procedures.md` — it told the next person on the
bench that this was a defect in our telemetry path. It now says to
identify the board by UID first, and gives the stale-`main.py` check.
