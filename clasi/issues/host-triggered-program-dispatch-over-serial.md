---
status: pending
---

# Host-triggered program dispatch (`RUN:<n>`) — needs serial arbitration first

`pxt-nezha-diffdrive` lets the host trigger a numbered program by
writing `RUN:<n>` over serial; the device dispatches to the matching
handler. That is a better bench loop than the current options here
(press a physical button, or drive the REPL).

## Why it is blocked, not just unimplemented

The TLM stream and the REPL/file-transfer channel **contend for the same
USB CDC link**. Today that contention is avoided by never having both
active: `tools/tour_run.py` drives the raw REPL (which suppresses
`main.py`), and telemetry comes back over that same session.

A `RUN:<n>` trigger implies `main.py` is running *and* the host is
writing to serial *and* telemetry is streaming back — three users of one
link. That needs an actual arbitration decision before any code:

- **Framed multiplexing** over the one CDC link (prefix/escape TLM
  frames so a command line is distinguishable), or
- **Move telemetry off USB** to the WiFi/radio path, leaving CDC for
  control, or
- **Half-duplex convention** — TLM pauses while a command is in flight.

[[tlm-stream-ignores-tlm-off]] is the same link, from the other end, and
should probably be decided together with this.

## Note

Do not implement the trigger before picking one of the above. A
`RUN:<n>` reader bolted onto the current unframed stream will appear to
work on a quiet link and corrupt under load, which is the worst of the
available failure modes.

## Provenance

Deferred out of [[deploy-user-programs-to-the-filesystem-freeze-only-firmware]].
Source repo: `/Volumes/Proj/proj/RobotProjects/pxt-nezha-diffdrive`.
