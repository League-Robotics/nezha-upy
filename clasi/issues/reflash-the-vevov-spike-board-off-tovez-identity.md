---
status: pending
---

# The vevov spike board announces `tovez`; decide its fate and reflash

One micro:bit on this bench, DAPLink UID
`9906360200052820b8e12372c44f4f67000000006e052820`, runs the **vevov
MicroPython spike** (`reference/vevov-micropython-spike-handoff.md`) and
announces itself over the v5 cleartext protocol as
`ID:diffdrive:tovez:1.0.0` — a name that belongs to a different
chassis.

It is not currently connected, which is why this is split out of
[[robot-identity-collision-and-stale-device-map]] rather than fixed
there.

## Why it still matters, given the guard rail landed

`tools/deploy.py` now refuses to deploy when the device names a
different robot, so this board can no longer *receive* the wrong
config. What it can still do is confuse a human: it answers `PING`,
`ID` and `VER`, and it floods `TLM:0:0:0` in a way `TLM:OFF` does not
stop (see [[tlm-stream-ignores-tlm-off]]). Both cost real bench time on
2026-08-20, and the guard rail does nothing about either — it protects
writes, not diagnosis.

## The decision to make first

The spike is a **reference artifact**, deliberately retained. So the
question is not just "reflash it" — it is which of these:

1. **Retire it.** The spike's findings are already written up in
   `reference/vevov-micropython-spike-handoff.md` and its `import robot`
   surface is superseded by the current firmware. Flash it with the
   normal image and deploy a real `data/vevov.json` (which does not
   exist yet — it would need creating, and per-robot calibration
   measured on that chassis).
2. **Keep it, correctly named.** Leave the spike image but fix the
   identity it announces, so it stops claiming tovez.
3. **Keep it as-is, and label it physically.** Cheapest. The board is a
   known-weird artifact; a piece of tape saying so may beat any code
   change.

Option 1 costs a calibration session. Option 3 costs nothing and fixes
the actual failure mode (a human misreading the bench). Do not default
to 1 just because it is the tidiest.

## When it is next on the bench

- `mbdeploy list` to confirm the UID before touching anything.
- `mpremote connect <port> fs ls` — check for a stale filesystem
  `main.py`, which is the leading hypothesis for the 2026-08-19 zetuv
  flood and would be worth confirming on a board that still has one.
  Capture it before erasing; the previous instance was destroyed by the
  mass erase that fixed it.
