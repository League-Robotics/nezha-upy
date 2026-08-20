---
status: pending
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
