---
status: pending
---

# WiFi-plane telemetry throttle is not wired — unbounded send-queue growth with TLM on

Found on the bench during sprint 007 ticket 010 (bench log
`docs/bench-log-tovez-wifi-2026-08-21.md` §20–21/§26). Recorded there
precisely; this issue is the fix-tracking record.

## The gap

`wifi_at.TlmThrottle` and `WifiAtLink.send_telemetry()` exist, are
unit-tested, and are named in PLAN.md's M4 gate (≥50 ms TLM floor on
the WiFi plane) — but nothing calls them. `comms.py`'s telemetry
emission path (post-v6-cutover) calls the unthrottled
`send_reliable()` on every ~24 ms pump tick, on every transport
uniformly.

## Measured consequence

With TLM non-off, `WifiAtLink._send_queue` grows without bound — each
datagram costs a full CIPSEND prompt/payload/SEND-OK exchange (tens of
ms), slower than the ~24 ms production rate. Confirmed live: after
only 8–25 s of TLM enabled, a TLM-off command's ack did not arrive
within 5 s (the queue backlog ahead of it). Memory grows until the
heap gives out.

## Why it wasn't a small bench fix

Where the throttle belongs is an architecture decision, not a patch:

- per-transport emission policy in `comms.py` (each transport declares
  its telemetry cadence/floor), or
- inside `WifiAtLink.send()` (transport self-defends, protocol stays
  ignorant), or
- bounded `_send_queue` with drop-oldest (the "drop a telemetry frame
  is documented policy" posture every other transport here takes).

The v5-era design routed telemetry through `send_telemetry()`
explicitly; the v6 cutover (sprint 007 ticket 006) rewired emission
generically over handlers and lost that plane-specific path.

## Confirmed in practice (sprint 007 ticket 011, 2026-08-22)

The "memory grows until the heap gives out" line above was a
prediction as of ticket 010; ticket 011's own bench session (`docs/
bench-log-tovez-wifi-2026-08-21.md` §28-29) found it already true on
arrival: the device was completely unresponsive on both the UDP
protocol plane and the TCP REPL mirror, with a repeating, uncaught
`MemoryError: memory allocation failed, allocating 2048 bytes` inside
`WifiAtLink.send()` (reached via `_emit_telemetry_cadence()` ->
`emit_telemetry()` -> `_write_line()`), printing once per scheduled-
pump tick, forever — the flood was severe enough that even
`mpremote`'s own raw-REPL entry handshake failed against it
("`could not enter raw repl`"). Recovery needed a hard reset
(`mpremote ... reset`, software-triggered over the existing USB
connection, not a physical act); a fresh boot showed no recurrence,
confirming the crash was accumulated queue state, not a fresh-boot
default. This is the same gap described above, now confirmed to reach
a fully wedged, unrecoverable-without-external-intervention state, not
just a delayed ack — worth weighting into whichever fix design
(per-transport policy, transport self-defense, or bounded queue with
drop-oldest) a future ticket picks.

## Interim bench discipline

Do not leave TLM enabled on the WiFi plane for more than a few
seconds; disable and expect a delayed ack. Sprint 007 ticket 011
inherits this discipline (its ticket notes point at the bench log).

## Related

[[retarget-v6-port-to-reliability-layer-draft]] — §8.5's telemetry
piggyback makes telemetry cadence the reliability heartbeat, which
raises the stakes on getting per-plane cadence right.
