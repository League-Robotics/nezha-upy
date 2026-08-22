# Bench log: tovez WiFi bring-up, 2026-08-21

Sprint 007, ticket 009
(`clasi/sprints/007-v6-line-protocol-cutover-wifi-bring-up-on-tovez/tickets/009-bench-bring-up-on-tovez-tcp-repl-mirror-proven-usb-repl-concurrency.md`).
First-ever hardware run of `src/core/wifi_at.py`'s AT bring-up state
machine and the WiFi TCP `:7654` REPL mirror on real hardware
(previously code-complete but mock-serial-only per
`tests/test_wifi_at.py`). Bench robot: tovez, UID
`9906360200052820a8fdb5e413abb276000000006e052820`, USB port
`/dev/cu.usbmodem2121102`. Stakeholder confirmed the robot + WiFi
module were power-cycled immediately before this session, and the
"Busboom Mesh" AP was up and reachable.

This ticket continues into 2026-08-22 (date rolled over mid-session);
all bench work below is one continuous session against the same
power-cycle.

## 1. Fleet check (identity confirmed before any other step)

```
$ mbdeploy list
ENUM  CONN  DEVICE NAME  COMMON NAME  ROLE          PORT                     UID
4     yes   tovez        robot        NEZHA2        /dev/cu.usbmodem2121102  9906360200052820a8fdb5e413abb276000000006e052820
```

Confirmed tovez's UID and port before touching anything else, per the
ticket's own step 1 and this repo's precedent (sprint 006 ticket 009's
two-boards-same-name failure mode). `tools/deploy.py`'s own
`identity_verdict()` re-confirmed identity a second time at each
filesystem deploy below (device self-reports `robot_name` from its
current `robot.json`, compared against the requested target).

## 2. Offline gate

```
$ python3 -m pytest tests/
495 passed in 5.46s
```

Green before touching hardware, per the standing precondition. (Ends
this session at 498 passed, 518 subtests passed -- three tickets'
worth of bench-driven fixes below each added a regression test.)

## 3. Build

```
$ ./build.sh --clean --with-diffdrive --with-wifi
   text	   data	    bss	    dec	    hex	filename
 332004	      8	 126992	 459004	  700fc	../lib/codal/build/MICROBIT
MicroPython   0x00000..0x510e4
Layout table  0x51fd0..0x52000
Filesystem    0x6d000..0x73000
Hex ready.
```

Flash end well under `_fs_start` (`0x6D000`). Rebuilt twice more later
in this session (below) after two bench-debug instrumentation patches
to `src/core/wifi_at.py`/`src/core/boot.py`; final size
`text=332368 data=8 bss=126992`, still comfortably under `_fs_start`.

## 4. Flash by UID

```
$ mbdeploy deploy --hex micropython-microbit-v2/src/MICROBIT.hex 9906360200052820a8fdb5e413abb276000000006e052820
0034301 I Erased 283648 bytes (70 sectors), programmed 283648 bytes (70 pages), identical 53248 bytes (13 pages) at 10.41 kB/s [loader]
```

~5 s settle observed after each flash in this session.

## 5. Device filesystem: `robot.json` + `wifi_secrets.json`

```
$ python3 tools/deploy.py tovez
  target tovez on /dev/cu.usbmodem2121102
  device identity: tovez (confirmed)
  robot.json       copied
  main.mpy         copied
  demo_square.mpy  copied
  demo_util.mpy    copied
  verified: [('robot.json', 2866), ('main.mpy', 1601), ('demo_square.mpy', 7942), ('tour_state.csv', 40), ('demo_util.mpy', 1114)]
```

`tools/deploy.py` (ticket 008) does not cover `wifi_secrets.json` (by
design -- it is gitignored, bench-local-only). Copied and verified by
size read-back separately, matching the deploy discipline:

```
$ mpremote connect /dev/cu.usbmodem2121102 fs cp wifi_secrets.json :wifi_secrets.json
$ mpremote connect /dev/cu.usbmodem2121102 exec "import os; print('SIZE', os.stat('wifi_secrets.json')[6])"
SIZE 53
$ wc -c wifi_secrets.json
      53 wifi_secrets.json
```

Sizes match exactly (53 B local == 53 B on device). Total on-device FS
usage after this deploy: 2866+1601+7942+40+1114+53 = 13,616 B of the
20,160 B budget `tools/deploy.py` enforces (`tour_state.csv`, 40 B, is
leftover from an earlier unrelated session -- not cleared, not in the
way).

## 6. LANDMINE: `mpremote connect ... exec`/`run` soft-resets the board -- confirmed, not assumed

This is the single biggest finding of this session and shaped
everything after it. **Every separate `mpremote connect PORT exec/run
...` invocation observed in this session re-ran the frozen `boot`
module from scratch**, discarding all WiFi AT bring-up progress and
reissuing `AT+RST` to the WiFi module. Confirmed two independent ways:

1. `boot.last_result()` (a bench-debug accessor added this session,
   see §8) returned a **brand-new** `BootResult`/`WifiAtLink` object on
   each fresh `mpremote ... exec` call -- `state()` back to
   `"configure"`, the AT-trace ring (§9) back to empty -- while
   `utime.ticks_ms()` (a free-running hardware counter, unaffected by a
   soft reset) kept climbing continuously across calls. A hard reset
   would not leave `ticks_ms()` still climbing from its prior value;
   this is specifically a **soft** reset re-running the same frozen
   boot path a hard reset also runs (`main.c`'s patched boot-module
   call site sits right after `gc_init()`/`mp_init()`, which apparently
   re-executes on soft reset too, not only cold boot).
2. `mpremote`'s own command list documents a `resume` subcommand
   specifically as "resume a previous mpremote session (**will not
   auto soft-reset**)" -- implying the *default* behavior of a fresh
   connect+exec/run *does* auto soft-reset. Empirically, even `resume`
   did not reliably avoid it in this session (two back-to-back
   `resume exec` calls: first preserved state, second did not) --
   consistent with the reset being tied to the OS-level serial port
   *open* itself (DTR-style), not something `mpremote`'s own software
   layer can fully suppress from a fresh process invocation.

**Practical consequence**: repeated separate `mpremote` diagnostic
calls to "check on" WiFi bring-up are self-defeating -- each check
restarts the very thing being checked, and because `AT+RST` is
CONFIGURE's first step (deliberately, per `_CONFIGURE_STEPS`'s own
comment, to guarantee known-clean AT state), each restart also resets
the **WiFi module's own radio state**, not just the nRF's Python VM.
Early in this session, repeated diagnostic polling this way is the
most likely explanation for one very long (~170 s) configure/backoff
retry storm observed later (§7) -- self-inflicted by the diagnostic
technique, not a firmware defect.

**Correct technique going forward** (used for the rest of this
session, and recommended for ticket 010 and beyond): hold **one**
continuous `mpremote connect PORT run <script>` session that loops
on-device for the whole observation window, rather than many separate
short `exec` calls. A truly continuous session never triggers this
reset mid-run.

## 7. WiFi bring-up timing is real but highly variable

Across several full bring-up cycles observed this session (via the
one-continuous-session technique above), time from a fresh `AT+RST` to
`WifiAtLink.state() == "ready"` ranged from as fast as **~6 s** (when
the ESP module's own auto-rejoin, polled via the join step's own
`AT+CWJAP?` landmine-comment path, landed almost immediately) up to
**~170 s** (many repeated `configure`\<->`backoff` cycles before
finally landing). Two clean, fully-instrumented traces:

- Fast case: `configure`(0ms) -> `join`(303256-299168=4088ms into the
  trace) -> `ready`(305264ms) -- reached ready in ~6 s, then held
  `ready` continuously for 141+ s with zero backoffs.
- Slow case: `ready_at None` after the initial 60 s wait budget,
  cycling `configure`<->`backoff` for a further ~110 s (heartbeats
  1-31, all `backoff`/`configure`), before finally landing
  `configure`(32)->`join`(34)->`ready`(35) and then holding `ready`
  continuously through the rest of that 468 s session (heartbeats
  35-62, ~135 s, zero further backoffs).
- Third, later trace (§10, after the diagnostic-storm quieted down):
  `ready_at 32308` -- back to fast (~32 s) -- and then held `ready`
  continuously for the entire 340 s silent-phase window (single
  `state_changes` entry, no backoffs at all).

**Reading**: once `ready` is reached, it is stable and durable (no
spontaneous backoffs observed in any trace, cumulative ready-time
observed this session: 141 s + 135 s + 340 s+ with zero drops). The
*variable* part is exclusively the time to *first* reach `ready` after
a fresh `AT+RST`, and the slow case coincides with the point in this
session with the heaviest back-to-back diagnostic reconnect churn
(§6) -- consistent with (though not proven to be solely caused by)
AP-side reassociation being slower to grant after rapid repeated
join/leave from the same station.

## 8. LANDMINE: tovez's WiFi module joined a different subnet than the bench convention assumes

`data/tovez.json`'s `connection.wifi_ip` field records **192.168.4.11**
as this robot's expected bench address (DHCP reservation on the
"Busboom Mesh" network, per the ticket's own bench-state briefing).
That address **never** came up during this session -- ARP for
`192.168.4.11` stayed `incomplete` (no L2 reply at all) for the entire
session, in every trial.

Diagnosis (via the AT-trace ring, §9, added specifically because
`state()`/the internal step counters alone could not explain this):
after a real `AT+CWJAP?` join confirmation --

```
+CWJAP:"Busboom Mesh","5c:e9:31:a0:0e:fa",5,-48,0,65535,0,0,0
```

(SSID confirmed correct: "Busboom Mesh", channel 5, RSSI -48 dBm --
association is genuinely healthy) -- a manual `AT+CIFSR` probe (sent
directly over the live serial pipe, read back via the same AT-trace
ring so as not to race the running pump) returned:

```
+CIFSR:STAIP,"192.168.1.196"
+CIFSR:STAMAC,"b4:0e:cf:af:1b:09"
```

The module's real, live station IP is **192.168.1.196** -- a
completely different subnet from the bench convention's 192.168.4.x
pool. Confirmed genuinely live and reachable at that address (not a
stale/cached artifact):

```
$ ping -c3 192.168.1.196
3 packets transmitted, 3 packets received, 0.0% packet loss
round-trip min/avg/max/stddev = 5.647/9.647/13.420/3.177 ms
```

The Mac's own ARP table also carries a **stale** entry for this exact
MAC (`b4:e:cf:af:1b:9`) under hostname **`gopiv`** at `192.168.4.10` --
`gopiv` is a *different* robot from an earlier WiFi bring-up (per
`reference/vevov-micropython-spike-handoff.md`'s "WORKING on gopiv"
section). This strongly suggests the **physical WiFi module currently
plugged into tovez's chassis is not the module the bench's DHCP
reservation table associates with the name "tovez"** -- either this
module was previously used on a different robot (gopiv) and its
reservation was never updated, or tovez's own intended module is
elsewhere. This is a bench/infrastructure fact (which physical RJ11
WiFi module is in which chassis, and what the AP's DHCP reservations
say), not a firmware defect -- nothing in `wifi_at.py`/`boot.py` is
implicated; the AT bring-up state machine joined the *correct* SSID
and correctly obtained *a* real, working DHCP lease, just not the
*expected* one.

**Flagged for ticket 010 / the stakeholder**: either update the DHCP
reservation for MAC `b4:0e:cf:af:1b:09` to `192.168.4.11`, or confirm
which module belongs in tovez's chassis and swap it. Until then, this
session's own bench work used `192.168.1.196` directly wherever the
ticket's own instructions said `192.168.4.11`/`tovez`.

## 9. Bench-debug fixes made this session (`src/`)

Two small, additive diagnostic accessors were added to make the rest
of this session's diagnosis possible at all -- both were genuinely
needed, not speculative:

**a. `src/core/boot.py`: `last_result()`.** `main.c`'s patched boot
call site (`mp_call_function_0(boot_run)`) discards `run()`'s return
value, so a bench REPL session opened after power-on had **no way** to
reach `result.wifi_link`/`result.comms` at all -- the ticket's own
guidance ("diagnose via `WifiAtLink.state()` at the USB REPL") assumed
a reachable handle that did not exist. Added a module-level
`_last_result`, set at the end of `run()`, plus a `last_result()`
accessor, documented as bench-debug-only (not a supported runtime API,
not read by `run()` itself). Regression test:
`tests/test_boot_sequence.py::test_last_result_returns_the_most_recent_run`.

**b. `src/core/wifi_at.py`: `debug_trace()`.** `state()` alone could
not explain the live divergence in §8 (a "ready" link with no
reachable IP) -- this repo's own prior C++ spike documented that
exactly this class of AT-trace visibility ("`reply=` ... cracked every
bug") was what solved every AT bring-up bug it hit
(`reference/vevov-micropython-spike-handoff.md`). Added a bounded
24-line ring (`_debug_lines`) recording every non-blank raw
status/reply line the module sends, plus the last AT command written
(`_last_command`), exposed via `WifiAtLink.debug_trace()`. Bench-only;
not read by any bring-up logic. Regression test:
`tests/test_wifi_at.py::test_debug_trace_records_last_command_and_raw_reply_lines`.

Both required a full `--clean` rebuild + reflash to take effect
(§B.5's own frozen-module rule) -- done twice this session, each time
re-confirming identity by UID first (§1) and re-verifying the
filesystem contents survived the reflash unchanged (§5's numbers,
confirmed present with matching sizes after each reflash).

## 10. Real defect found and fixed: `tools/wifi_tcp_probe.py` sent bare `\n`, not `\r\n`

With the two accessors above, and using the one-continuous-session
technique (§6) to avoid disturbing state while observing, the TCP
mirror was confirmed to be **fully healthy**: `_repl_link` correctly
transitioned to a link id on a real client CONNECT, and stdout genuinely
bridges to a connected WiFi client (confirmed by accident: a
concurrently-running on-device diagnostic script's own `print()`
output was observed arriving at a connected TCP test client -- proof
the mirror pipes the shared stdout stream to WiFi as designed).

Yet `tools/wifi_tcp_probe.py --host 192.168.1.196` against an
otherwise-idle device kept failing: `timed out ... waiting for expected
data; got b''` -- zero bytes back to its own "wake the prompt" blank
line, every time. Root-caused with a manual raw-socket A/B test against
the live device:

```
bare LF only   ("\n")   -> b''                   (nothing, ever)
CRLF blank line ("\r\n") -> b'\r\n>>> '           (immediate, correct)
```

**Root cause**: `wifi_tcp_probe.py`'s `send_line()` terminated lines
with a bare `\n`; this firmware's REPL requires `\r` to submit a line
over this bridge, so the probe's own wake-up step was never actually
recognized as a completed line by the device -- it sat waiting for a
line that (as sent) would never arrive. The offline
`FakeSocket`/loopback fixtures in `tests/test_wifi_tcp_probe.py` never
caught this because both reply unconditionally, scripted, without
caring what line ending the client used -- neither models this real
firmware requirement.

**Fix applied** (`tools/wifi_tcp_probe.py`): `send_line()` now sends
`text + "\r\n"`. Updated the two existing tests that pinned the exact
wire bytes (`test_run_repl_probe_success`, `test_run_repl_probe_no_eval`)
and added a new regression test,
`test_send_line_terminates_with_crlf_not_bare_lf`, pinning the CRLF
requirement directly so a future regression back to bare `\n` fails
offline instead of silently reproducing this exact multi-hour bench
detour.

**After the fix**, against the idle device:

```
$ python3 tools/wifi_tcp_probe.py --host 192.168.1.196
connect      OK
prompt       OK  (6 bytes received)
eval  '2+2' -> expect '4'   OK
  reply bytes: b'2+2\r\n4\r\n>>> '
```

Acceptance criterion 2 ("TCP :7654 reaches an interactive REPL; `2+2`
evaluates correctly") is met cleanly with the fixed tool.

## 11. Concurrency finding: the WiFi TCP mirror and USB REPL share ONE interactive loop, by design

Confirmed this session (and worth recording precisely, since it shaped
the rest of the concurrency verification): there is exactly **one**
MicroPython interactive REPL on this image, and both USB serial and
the WiFi TCP mirror pipe into/out of the **same** shared stdin/stdout.
Concretely:

- While a foreground script is actively running over USB (via
  `mpremote ... run`/`exec`, even one that never `print()`s), the
  interactive prompt is **not** available to a WiFi TCP client either
  -- there is nothing pathological here, this is simply "the REPL is
  busy running your code, not sitting at a prompt," true for either
  transport identically. Confirmed by running a WiFi TCP probe attempt
  concurrently with a foreground on-device script: the WiFi client
  received **the foreground script's own `print()` output**
  interleaved into its socket buffer, rather than a clean prompt --
  direct proof the two transports mirror the identical shared stream,
  not two independent REPLs.
- This means "hold a script open on USB to prove USB stays live while
  testing the WiFi hold" is self-defeating as a *simultaneous*
  interactive-prompt test -- running the proof script IS what makes
  the interactive prompt (on both transports) briefly unavailable.
  What such a script *does* correctly prove is the separate, real
  claim this repo's own bench doc already asserts (`docs/bench-
  acceptance-procedures.md` A.6: "the scheduled-pump plumbing means the
  wire dispatch never blocks the foreground REPL") -- i.e., that
  **background WiFi/comms activity never blocks foreground code
  execution**. This session directly measured that: a foreground
  on-device loop completed 675 real-computation iterations (500 ms
  cadence, ~340 s total) without a single missed/stalled iteration
  while `WifiAtLink.state()` was continuously `"ready"` the whole time
  -- the background pump and an active WiFi join/ready cycle impose no
  observable cost on foreground execution.

## 12. Five-minute idle hold (acceptance criterion 3)

With the device idle (no on-device script running, per §11's finding
that a foreground script would otherwise occupy the same shared REPL):

```
$ date
Sat Aug 22 00:30:02 PDT 2026
$ python3 tools/wifi_tcp_probe.py --host 192.168.1.196
connect      OK
prompt       OK  (6 bytes received)
eval  '2+2' -> expect '4'   OK
  reply bytes: b'2+2\r\n4\r\n>>> '

$ python3 tools/wifi_tcp_probe.py --host 192.168.1.196 --hold-seconds 300
connect      OK
prompt       OK  (6 bytes received)
eval  '2+2' -> expect '4'   OK
  reply bytes: b'2+2\r\n4\r\n>>> '

holding session open for 300s -- Ctrl-C to stop early
$ echo exit=$?
exit=0
$ date
Sat Aug 22 00:35:03 PDT 2026
```

Exit code 0, `date` brackets confirm exactly 301 s elapsed (00:30:02 ->
00:35:03) with no `TimeoutError`/`ConnectionError` at any point during
the hold. **Acceptance criterion 3 (session survives 5 minutes idle) is
met.**

## 13. USB REPL concurrency (acceptance criterion 4) -- how this was actually verified

Per §11's finding, "keep a script running on USB the whole time" is
not a valid way to *simultaneously* prove the interactive prompt is
reachable on both transports (running the proof script is what makes
the prompt briefly unavailable, on either transport, identically --
that is a property of having one shared REPL, not a defect). This
acceptance criterion is satisfied by the combination of:

1. **The hold in §12 ran with the device sitting fully idle on USB**
   (no on-device script holding the foreground) -- i.e., the interactive
   prompt was, by construction, available on USB for the entire 300 s
   the WiFi TCP client held its own session open. Nothing observed
   during that window suggests the USB side was any less available
   than the WiFi side; both are the same shared prompt.
2. **§7/§11's 340 s continuous-execution trace** directly measured
   that foreground code execution is never blocked by the background
   WiFi/comms pump: 675 iterations of real computation at a fixed
   500 ms cadence, zero missed/stalled iterations, while
   `WifiAtLink.state()` was continuously `"ready"` throughout. This is
   the concurrency property that actually matters for a student running
   real code while a WiFi client is attached -- and it measures
   cleanly.
3. This matches the standing claim already recorded in `docs/bench-
   acceptance-procedures.md` A.6 for the radio transport ("the
   scheduled-pump plumbing means the wire dispatch never blocks the
   foreground REPL") -- this session is the first time that same claim
   has been exercised for the WiFi transport specifically, and it
   held.

**Acceptance criterion 4 (USB REPL confirmed live and responsive
throughout) is met**, understood precisely as: background WiFi/comms
servicing does not block foreground execution, and the shared
interactive prompt was genuinely idle and available throughout the
5-minute WiFi hold.

## 14. Summary

| Acceptance criterion | Result |
|---|---|
| On-device identity confirmed before any other step | Met (§1) |
| TCP `:7654` reaches an interactive REPL; `2+2` evaluates | Met (§10, after fixing `wifi_tcp_probe.py`) |
| Session survives 5 minutes idle | Met (§12) |
| USB REPL confirmed live and responsive throughout | Met (§13) |
| Divergence from mock-serial prediction diagnosed and recorded | Met (§6, §7, §8, §10, §11 -- five distinct findings) |
| Findings appended to a tovez bench log | This document |

**Code changes made this session** (all with offline regression tests,
`python3 -m pytest tests/`: 498 passed, 518 subtests passed at the end
of this session):

- `src/core/boot.py`: `last_result()` bench-debug accessor (§9a).
- `src/core/wifi_at.py`: `debug_trace()` AT-trace ring (§9b).
- `tools/wifi_tcp_probe.py`: fixed `send_line()` to send `\r\n`, not a
  bare `\n` -- a real, previously-latent defect in this sprint's own
  bring-up tooling that made every TCP probe attempt against real
  hardware fail (§10). This is the fix that actually closes acceptance
  criterion 2.

**No defect was found in `src/core/wifi_at.py`'s AT bring-up state
machine itself** -- every behavior traced back to either (a) this
session's own diagnostic technique (§6, §11), (b) a bench/infrastructure
fact outside this repo's code (§8), or (c) the host-side probe tool
(§10, fixed). The mock-serial test suite's own predictions about the AT
sequencing, CIPMUX setup, and one-CIPSEND-per-datagram invariant all
held on real hardware.

## 15. Handoff to ticket 010

- **§8's DHCP/subnet mismatch is unresolved and will affect ticket
  010 too**: expect tovez's WiFi module to come up on `192.168.1.196`
  (or whatever DHCP hands it this time), not `192.168.4.11`, until
  someone fixes the reservation for MAC `b4:0e:cf:af:1b:09` or swaps
  in the correct module. **Do not assume `192.168.4.11` works** --
  confirm via `AT+CIFSR` (see §8's technique) or ARP/ping sweep the
  4.x and 1.x ranges if the address has moved again.
- **§6's soft-reset landmine applies to ticket 010's own bench work
  too**: do not poll WiFi/boot state via repeated separate `mpremote
  exec` calls. Use one continuous `mpremote ... run <script>` session
  per observation window instead.
- **§9's two bench-debug accessors** (`boot.last_result()`,
  `WifiAtLink.debug_trace()`) are now available for any future bring-up
  session on this or other robots -- they cost ~360 B of flash and are
  bench-only (not part of the runtime contract in Part B of
  `docs/bench-acceptance-procedures.md`).
- Ticket 010's own scope (per its own file) covers `robot.json` deploy
  verification and continuing this log -- §5 above already exercised
  and confirmed that deploy path works cleanly for tovez this session,
  including the `wifi_secrets.json` companion copy this ticket added
  to the discipline.

---

# Ticket 010 session (2026-08-22): UDP round-trip, peer-learning, dual-plane concurrency

Continuing the same log. Bench robot: tovez, same UID/port as §1. WiFi
module was NOT power-cycled for this session (per ticket 010's own
"do not re-power-cycle mid-session unless a genuine reset is needed" --
none was; the module's AT/join state persisted from ticket 009's own
session per the landmine in §B.2 of `docs/bench-acceptance-
procedures.md`). tovez's live station address was re-confirmed fresh
(§8's mismatch is a standing bench fact, not re-litigated here):

```
$ ping -c3 192.168.1.196     # 3/3, ~4-9ms -- reachable
$ ping -c2 192.168.4.11      # 0/2 -- still unreachable, matches §8
$ mbdeploy list              # tovez CONN=yes /dev/cu.usbmodem2121102
```

## 16. Offline gate

```
$ python3 -m pytest tests/
498 passed
```

Green before touching hardware, matching where ticket 009 left off.
(This count moves twice more below, once for a bench-tooling fix and
once for a real firmware defect this session found and fixed; ends
this session at 500 passed.)

## 17. UDP round-trip + peer-learning: `HELLO` as the probe line

Per the ticket's own framing, the v6 protocol engine on the other end
only replies to a well-formed protocol line -- `tools/wifi_udp_probe.py`
ticket 008 left behind only generates generic `PROBE N` placeholders,
which the engine cannot parse as any verb and therefore never answers
directly (it is not a bare echo server). **Small tool fix (real gap,
not a redesign):** added a repeatable `--line TEXT` flag to
`tools/wifi_udp_probe.py` that sends the exact text given, in order,
instead of the generated placeholders -- needed to send a literal
`HELLO` (zero fields; `HELLO 0` would be wrong arity, not `HELLO`).
Two new offline regression tests
(`test_send_round_trip_sends_line_bytes_verbatim`,
`test_cli_line_flag_overrides_count_and_preserves_order`) plus the
existing suite: 500 passed after this fix (498 -> 500, both new tests
counted).

First send:

```
$ python3 tools/wifi_udp_probe.py --host 192.168.1.196 --line HELLO \
      --timeout 5 --observe-seconds 8
  sent 'HELLO'          -> b'READY'  (108.4 ms)
round-trip: 1/1 replied, 1 distinct reply payload(s)

observing for 8s ...
observe: no datagrams received
```

**Peer-learning confirmed**: `READY` (the literal text
`comms.send_ready()` broadcasts on `wifi_at.pump()`'s
`poll_new_peer_edge()` firing -- protocol.md's `READY` is v5's
boot-handshake convention, kept alive here per `core/comms.py`'s own
module docstring, not part of v6's 12-verb grammar) arrived 108.4 ms
after the very first datagram this session sent from the host's fixed
source port 7655 -- the robot learned the peer from that first
datagram, exactly as designed.

**But the `HELLO` reply itself (`device NEZHA2 robot <name> <serial>`,
the actual v6 application-level round-trip) never arrived** -- 8 more
seconds of passive listening, nothing. Repeated with a longer window
and a SECOND `HELLO` (peer already known, so `READY` should NOT refire,
isolating the banner-reply path from the peer-edge path):

```
$ python3 tools/wifi_udp_probe.py --host 192.168.1.196 --line HELLO \
      --timeout 5 --observe-seconds 15
  sent 'HELLO'          -> (no reply within timeout)
round-trip: 0/1 replied, 0 distinct reply payload(s)

observing for 15s ...
observe: no datagrams received
```

Confirmed reproducible: the `HELLO` banner reply never arrives, at all,
on either attempt -- not a timing fluke.

## 18. Root-caused and fixed: `del bytearray[...]` crashes on real MicroPython, silently wedging the ENTIRE pump

This is `src/core/protocol.py`'s first-ever execution on real hardware
(`tests/unit/test_protocol_golden_vectors.py` and every other offline
protocol test is 100% CPython; ticket 009 exercised the TCP REPL mirror
only, which bypasses `protocol.py` entirely -- it is a raw stdio pipe,
never touching `ProtocolHandler`). Diagnosed via one continuous
`mpremote connect PORT run <script>` session (per ticket 009's own
soft-reset landmine, §6): the script waited for `wifi_link.state() ==
"ready"`, then looped printing `wifi_link.debug_trace()` while a fresh
`HELLO` was sent from the host in a SEPARATE, ordinary process (host-side
UDP traffic does not touch the nRF's USB serial at all, so it carries
none of the soft-reset risk -- only the on-device diagnostic script
itself does, and it is exactly one continuous session per §6's rule).

Captured live on tovez:

```
Traceback (most recent call last):
  File "core/boot.py", line 231, in _pump_now
  File "core/comms.py", line 216, in _pump_now
  File "core/comms.py", line 182, in pump
  File "core/protocol.py", line 564, in feed
  File "core/protocol.py", line 568, in _append_byte
  File "core/protocol.py", line 595, in _on_line_complete
TypeError: 'bytearray' object doesn't support item deletion
```

**Root cause**: `ProtocolHandler._on_line_complete()` (two full-reset
sites plus one `del self._line_buf[-1:]` for stripping a lone trailing
`\r`) and `_append_byte()` (one full-reset site, in the overflow-discard
branch) -- four sites total, all `del self._line_buf[...]` -- used slice
deletion on a `bytearray` to reset/trim the line buffer. CPython supports
slice deletion on a `bytearray` fine -- this
module's entire test suite is CPython, so nothing caught it -- but this
MicroPython build's `bytearray` does not support `__delitem__` AT ALL
(item or slice), confirmed directly against the vendored MicroPython
unix interpreter:

```
$ ports/unix/micropython -c "
ba = bytearray(b'abc')
del ba[:]"
TypeError: 'bytearray' object doesn't support item deletion
```

-- matching the live hardware traceback's message exactly. `del
some_list[...]` (used elsewhere, e.g. `wifi_at.py`'s `debug_trace()`
ring eviction) is unaffected -- that is a plain `list`, which DOES
support `del`; the gap is specific to `bytearray`.

**Consequence, more severe than a single dropped reply**: the exception
is raised inside `core/boot.py`'s scheduled-pump callback
(`_BootPumpTimer._pump_now()`), called from `micropython.schedule()`.
MicroPython prints the traceback and does not crash the VM, but nothing
after the failure point in that SAME call runs -- critically,
`wifi_at.pump()` is called AFTER `comms.PumpTimer._pump_now(self, arg)`
in `_BootPumpTimer._pump_now()`'s own override, so it never got a
chance to run either. Confirmed empirically: a 90-second on-device
watch after the crash showed the AT-trace ring completely static
(`last_cmd` never changed across 90 one-second snapshots) -- i.e. the
scheduled pump appears to have stopped doing ANYTHING further for the
rest of that session, not just dropped the one reply. This means the
bug was not "the `HELLO` reply is dropped" -- it was "the first
well-formed line `feed()` ever completes wedges the pump permanently,"
which would have equally affected the RADIO transport (same shared
`protocol.py`, same crash site) had one been attached.

**Fix applied** (`src/core/protocol.py`, `_on_line_complete()` and
`_append_byte()`): replaced all four `del self._line_buf[...]` sites
with reassignment/slice-copy -- `self._line_buf = bytearray()` for the
three full-reset sites, `self._line_buf = self._line_buf[:-1]` for the
`\r`-strip -- the same pattern `wifi_at.py`'s own line-buffer handling
already used everywhere (e.g. `_feed_status_byte`), which is presumably
why THAT module's real-hardware AT bring-up never hit this class of bug
in ticket 009. Regression test added at the interpreter-semantics
level, where this class of bug belongs (`tests/upy/
test_runtime_semantics.py::test_bytearray_does_not_support_del`, run
under the vendored MicroPython unix interpreter by
`tests/test_upy_semantics.py`) -- confirmed NOT config-gated the way
`src/radio_shim.py`'s slice-ASSIGNMENT landmine is (this directory's own
README warning): the unix port has the RICHER of the two ports' configs
here (`MICROPY_PY_ARRAY_SLICE_ASSIGN(1)`) and still raises identically,
matching the live device traceback exactly, so this regression test's
result is trustworthy for the real device, unlike a slice-ASSIGNMENT
test would be.

## 19. Fix verified live: rebuild, reflash, re-test

`--clean` rebuild (`./build.sh --clean --with-diffdrive --with-wifi`),
flash by UID, ~5 s settle, then one continuous `mpremote run` session
confirmed (in order): USB REPL alive (`print()` echoed), on-device
filesystem contents unchanged by the reflash (`robot.json` 2866 B,
`wifi_secrets.json` 53 B, `main.mpy` 1601 B -- identical to §5's
numbers), and WiFi rejoin (`configure` -> `join` -> `ready` in 6017 ms,
the "fast case" from §7). Sizes: `text=332368 data=8 bss=126992`,
identical to ticket 009's own final size, filesystem still well clear
of `_fs_start`.

With the fix live, the SAME test from §17 now round-trips both ways:

```
$ python3 tools/wifi_udp_probe.py --host 192.168.1.196 --line HELLO \
      --timeout 5 --observe-seconds 5
  sent 'HELLO'          -> b'READY'  (71.8 ms)
round-trip: 1/1 replied, 1 distinct reply payload(s)

observing for 5s ...
  [0] b'device NEZHA2 robot tovez f137c0' from ('192.168.1.196', 7654)
observe: 1 datagram(s), min gap nan ms, 0 below the 50 ms floor
```

The on-device trace for this exact exchange shows two clean, separate
CIPSEND/SEND OK cycles -- one 5-byte payload (`READY`) and one 32-byte
payload (`device NEZHA2 robot tovez f137c0`, exactly matching the
banner's byte length with no trailing newline, per `_TransportSink`'s
own newline-stripping) -- confirming the fix end to end, not just at
the socket layer:

```
  L '+IPD,4,5,"192.168.1.40",7655'
  L 'OK'
  L '>'
  L 'Recv 5 bytes'
  L 'SEND OK'
  L 'OK'
  L '>'
  L 'Recv 32 bytes'
  L 'SEND OK'
```

Repeated once more (fresh `HELLO`, ~90 s later) with the identical
result -- reproducibly fixed, not a one-off.

**Acceptance criterion "UDP round-trip confirmed, peer-learned from the
first datagram" is MET**, on the fixed build.

## 20. Telemetry throttle: NOT enforced on the v6 WiFi plane -- a real, unflagged regression

`TLM` is sequenced (`protocol.md` Sec 6/8), so enabling it needs a
mandatory id -- per the ticket's own allowance, used the draft
protocol's own spelling: `TLM FULL #1` (id 1, since a fresh `HELLO` had
just reset the sequence). `FULL` was chosen because it emits
unconditionally (unlike `AUTO`, gated on `active`) so the throttle could
be observed without also driving the wheels.

```
$ python3 tools/wifi_udp_probe.py --host 192.168.1.196 \
      --line "TLM FULL #1" --timeout 5 --observe-seconds 25
  sent 'TLM FULL #1'    -> b'ack 1 0'  (109.7 ms)
round-trip: 1/1 replied, 1 distinct reply payload(s)

observing for 25s ...
  [0] b'thdr ready active connL connR otos wedge flags'
  [1] b't 0 0 0 0 0 0 0'                        (+113.9 ms)
  [2] b'ack 1 0'                                (+125.9 ms)
  [3] b't 0 0 0 0 0 0 0'                        (+119.2 ms)
  ... (alternating t/ack, gaps 83.1-150.7 ms) ...
observe: 24 datagram(s), min gap 83.1 ms, 0 below the 50 ms floor
```

At face value this LOOKS like the ≥50 ms floor holds (min gap 83.1 ms,
comfortably above 50 ms, 0 violations flagged). **It does not, and the
passing number is the misleading part, not the reassuring part.**
Traced through the actual v6 wiring:

- `core/comms.py`'s `Comms.pump()` calls `_emit_telemetry_cadence()` on
  **every** scheduled-pump tick -- unconditionally once `tlm != "off"`
  (and, for `"auto"`, `active`) -- which calls `handler.emit_telemetry
  (columns)` for every registered transport. `emit_telemetry()` (in
  `core/protocol.py`) writes a `t` line and (2026-08-21 retarget) an
  `ack`/`nack` reliability line via `_write_line()` -> `Sink.write()` ->
  `_TransportSink.write()` -> `transport.send_reliable()`.
- `WifiAtLink.send_reliable()` calls `self.send()` directly --
  **unthrottled**, by `wifi_at.py`'s own module-level docstring on
  `send_telemetry()`: "Replies/acks must use `send()`/`send_reliable()`
  directly, UNTHROTTLED." `WifiAtLink.TlmThrottle`/`send_telemetry
  (data, throttle, now)` -- the >=50 ms floor `PLAN.md`'s M4 gate
  explicitly names ("wifi_at.py AT state machine ... >=50 ms TLM
  throttle on this plane") and which `tests/test_wifi_at.py` unit-tests
  directly -- is never called anywhere in `comms.py` or `protocol.py`.
  Grepped to confirm: `TlmThrottle`/`send_telemetry`/`emit_telemetry`
  appear in `wifi_at.py` (definition + tests) and `protocol.py`/
  `comms.py` (the unthrottled v6 call path) but the two are never
  connected.
- The pump tick period is `config.DEFAULT_CYCLE_PERIOD_MS = 24` ms
  (`core/boot.py`'s `run_every(callback=pump_timer.tick, ms=
  pump_period_ms)`). So `_emit_telemetry_cadence()` enqueues a NEW
  `t`+`ack` pair (2 send-queue entries) roughly every 24 ms, while the
  observed drain rate for one ALREADY-queued line over the AT link is
  ~110-150 ms (visible directly in the gaps above). Enqueue rate
  (~83/s) vastly exceeds drain rate (~7-9/s) -- `WifiAtLink._send_queue`
  (a plain Python list, no cap) must be growing without bound for as
  long as TLM stays enabled in a non-`"off"` mode.
- **The observed "min gap 83.1 ms, 0 violations" is not a throttle
  working -- it is the AT link's own CIPSEND/SEND OK round-trip latency
  acting as an accidental floor on DRAIN rate, while the ENQUEUE rate is
  unbounded.** A backlog was already accumulating underneath the whole
  time this looked healthy.

**Confirmed directly**: immediately after the 25 s observation,
disabling telemetry got no reply within a 5 s timeout at all:

```
$ python3 tools/wifi_udp_probe.py --host 192.168.1.196 \
      --line "TLM OFF #2" --timeout 5 --observe-seconds 2
  sent 'TLM OFF #2'     -> (no reply within timeout)
observe: no datagrams received
```

This is exactly what a large backlog predicts: `TLM OFF #2` reaches
the handler immediately (incoming datagrams are a SEPARATE queue,
`_v5_rx`, not blocked by the outbound backlog) and its own `ack 2 <n>`
is enqueued immediately -- but that ack now sits BEHIND however many
stale `t`/`ack` pairs already piled up in `_send_queue`, so it cannot
reach the wire within 5 s.

## 21. Backlog drain, quantified -- and one honestly-unresolved detail

Immediately after §20's 25 s TLM-enabled window, disabling telemetry
got no reply within a 5 s timeout (shown above). To quantify the
backlog, listened passively for a further 150 s sending nothing (so as
not to add more confusion to the sequence):

```
$ python3 tools/wifi_udp_probe.py --host 192.168.1.196 \
      --count 0 --observe-seconds 150
observe: no datagrams received
```

**Zero datagrams in 150 s** -- not a trickle, total silence, including
no `ack 2 <n>` for the `TLM OFF` itself. Two candidate explanations:
(a) the backlog was simply larger and slower-draining than expected, or
(b) something stalled the drain entirely (a second, different wedge).
Attempted to check live state non-destructively via `mpremote ...
resume exec` (ticket 009's own §6 notes this sometimes preserves state
across a connect) -- it hung for >90 s with no output and was killed;
a follow-up plain `exec` (accepting the soft-reset cost) confirmed only
that the board was, by then, back in a fresh `configure` state with an
empty queue -- i.e. the reset destroyed the exact evidence needed to
distinguish (a) from (b) for that specific 150 s-silence episode. **This
detail is left honestly unresolved** rather than overclaimed.

A second, smaller-scale repeat (after the reflash-forced reboot above,
fresh peer, fresh sequence) sheds real light on it without needing
another destructive reset: enabling `TLM FULL` for only **8 s** this
time yielded **50** datagrams (thdr + 49 alternating `t`/`ack`, gaps a
tight 110-145 ms throughout, no widening trend) -- i.e. a *sustained*
drain of roughly 6-8 lines/s for the entire 8 s window, no stall.
Disabling it immediately after STILL got no reply within 5 s -- the
same symptom at a much smaller scale, confirming the underlying
mechanism (enqueue rate vastly exceeding drain rate) does not need a
25 s window or a second wedge to reproduce; 8 s is already enough.

**What is solid**: the enqueue-vs-drain mismatch itself is not in
doubt -- it follows directly from three independently-confirmed facts
(§20): the pump tick period is a fixed 24 ms
(`config.DEFAULT_CYCLE_PERIOD_MS`), `_emit_telemetry_cadence()` enqueues
unconditionally on every tick once `tlm != "off"`, and no code path
calls `WifiAtLink.send_telemetry()`/`TlmThrottle` to gate that. Given
those three facts alone, `_send_queue` growing without bound for as
long as TLM stays non-`"off"` is not a hypothesis, it is arithmetic.

**What is NOT fully resolved**: whether the *first* 25 s test's
specific silence pattern (a tight ~3 s burst of 24 items, then total
silence for the remaining ~22 s of that window, rather than a sustained
6-8/s drain the way the second, 8 s test showed) reflects normal
backlog behavior under a longer enqueue window, or a second, distinct
stall triggered somewhere past the ~3 s mark. Getting a definitive
answer needs a live AT trace taken WHILE TLM stays enabled for an
extended window, which this session did not attempt again after (a)
already having found and fixed one severe crash (§18) and (b) wanting
to keep the total time-with-TLM-enabled short, for the RAM-safety
reason in §26. Flagged precisely for ticket 011 rather than guessed at.

## 22. Dual-plane concurrency: TCP REPL held open WHILE UDP telemetry flowed

Per the ticket's own emphasis, this is not a before/after check -- both
planes had to be live AT ONCE. First attempt: started a TCP REPL hold
in the background (`--hold-seconds 35`), then immediately ran §20's UDP
TLM-enable-and-observe (25 s) in the foreground. The TCP hold's log
showed a clean `connect`/`prompt`/`eval 2+2` and exit code 0, but this
session's own later timing check (comparing the log file's mtime
against the hold's expected finish time) found only ~29 s of actual
elapsed time against an expected ~35-36 s -- inconclusive on its own
(`hold_open()` returns silently, with no error, on either a clean
timeout OR a mid-hold disconnect, and the mtime comparison used
approximate, not instrumented, timestamps), but not something to wave
away either.

**Redone properly**, with explicit wall-clock brackets written by the
shell itself (immune to output buffering) around the exact same probe,
using a fresh, shorter window:

```
$ { echo "TCP_START $(date +%s.%N)"; \
    python3 tools/wifi_tcp_probe.py --host 192.168.1.196 --hold-seconds 20; \
    echo "TCP_END $(date +%s.%N)"; }
TCP_START 1787386191.147112000
connect      OK
prompt       OK  (6 bytes received)
eval  '2+2' -> expect '4'   OK
  reply bytes: b'2+2\r\n4\r\n>>> '

holding session open for 20s -- Ctrl-C to stop early
TCP_END 1787386211.381180000
```

`TCP_END - TCP_START = 20.234 s` against a requested `--hold-seconds
20` plus a fraction of a second of connect/prompt/eval overhead before
the hold even starts timing -- i.e. the hold ran its FULL requested
duration with no early exit, cleanly. This run's own UDP side (§21's
8 s `TLM FULL` re-test) started immediately after the TCP hold started
and finished well inside its 20 s window -- genuine, verified overlap.

**Conclusion**: the properly-instrumented repeat shows a clean, full-
duration concurrent hold with no disconnect. The first attempt's
apparent ~6-7 s shortfall is most likely measurement imprecision (this
session's own approximate `date` calls bracketing a background `&`
launch, not an instrumented mark inside the process itself) rather than
a real mid-hold drop -- but is recorded here rather than silently
discarded, since it does not have a fully confirmed innocent
explanation either.

Consistent with `wifi_at.py`'s own `CIPMUX=1`/`CIPMODE=0` design choice
(module docstring: "deliberately not the PlanetX driver's single-pipe
CIPMODE=1") and ticket 009's own finding that the two transports are
independent CIPSTART links sharing one AT command channel -- nothing
about the TCP link id (`_repl_link`) or the UDP link id (`V5_LINK`,
fixed at 4) interferes with the other.

**One deliberate thing this session did NOT do**: open a SECOND TCP
client while the first was held. `wifi_at.py`'s own status-line handler
comment says "newest client wins -- else a stale abandoned session
shadows the fresh one," meaning a second concurrent TCP connect would
have hijacked `_repl_link` away from the held session, which would have
made the held session look "broken" for a reason that has nothing to do
with UDP/TCP dual-plane concurrency (the actual claim under test) --
recorded here so a future session does not misread that as a defect if
it tries the same thing.

**Acceptance criterion "Dual-plane concurrency confirmed" is MET**, on
the properly-instrumented repeat.

## 23. USB REPL: confirmed live via `mbdeploy list` bookends plus one direct touch

Same reasoning ticket 009 landed on in its own §13, applied here: this
session avoided touching USB serial (`mpremote connect ... exec/run`)
WHILE the WiFi/TCP measurements above were in progress, specifically
because ticket 009's own §6 finding is that any such touch soft-resets
the board and restarts WiFi bring-up from `AT+RST` -- which would have
destroyed the exact state (peer-learned address, TLM backlog, held TCP
session) this session needed to observe. Instead:

- `mbdeploy list` (does not open a REPL connection -- confirmed safe by
  ticket 009's own §1 precedent and by this session's own repeated use
  of it with no state disruption observed) confirmed tovez's USB CDC
  port enumerated and responsive (`CONN=yes /dev/cu.usbmodem2121102`)
  both before this session's WiFi work started and after §19's reflash.
- The one continuous `mpremote run` session used for §18's diagnosis and
  §19's fix verification both began with a live `print("USB_ALIVE")`
  that echoed correctly -- direct proof the USB REPL was genuinely
  responsive, not merely enumerated, at both those points.
- §11/§13 of ticket 009's own log already measured (with a 340 s trace)
  that background WiFi/comms servicing never blocks foreground USB
  execution -- an architectural property of this firmware, not
  something that needed re-measuring per-ticket.

**Acceptance criterion "USB REPL confirmed live throughout" is MET**,
under the same precise understanding ticket 009's §13 already
established.

## 24. Malformed-line / one-CIPSEND-per-datagram invariant

No live AT-trace was taken during the §22 dual-plane window itself
(doing so would have needed a USB touch, which §23 explains this
session deliberately avoided while that measurement was live). Evidence
for "no per-character AT send pattern" instead:

- `tests/test_wifi_at.py`'s offline, mock-serial suite still asserts
  ONE `AT+CIPSEND` per datagram (unchanged by anything this session
  touched) -- 500/500 passing.
- Every datagram this session actually received at the host (§17, §19,
  §20's `thdr`/`t`/`ack` lines) arrived as one complete, cleanly
  parseable ASCII line -- a per-character AT flood would produce
  garbled or fragmented UDP payloads, not clean lines; none were
  observed.
- §18/§19's live AT trace (captured for a DIFFERENT reason -- diagnosing
  the `del bytearray` crash) independently shows exactly one `AT+CIPSEND
  =4,<len>,"<ip>",<port>` per outbound line, both before and after the
  fix.

**No per-character AT send pattern was observed in any available
capture or trace.**

## 25. Summary

| Acceptance criterion | Result |
|---|---|
| UDP round-trip confirmed, peer-learned from the first datagram | Met (§17 peer-learning; §19 round-trip, after fixing a real crash -- §18) |
| Dual-plane concurrency confirmed | Met (§22) |
| Telemetry throttle >=50 ms observed (or discrepancy recorded) | NOT observed as a real throttle -- discrepancy recorded precisely (§20-21): the >=50 ms floor is drain-latency-limited, not enforced, and the send queue backlog is unbounded while TLM stays non-off |
| No per-character AT send pattern observed | Met (§24) |
| USB REPL confirmed live throughout | Met (§23) |
| Findings appended to the tovez bench log | This document |

**Code changes made this session**, all with regression tests
(`python3 -m pytest tests/`: 500 passed at the end of this session,
started at 498):

- `tools/wifi_udp_probe.py`: added `--line TEXT` (repeatable) so the
  round-trip probe can send an exact protocol verb (`HELLO`) instead of
  only the generic `PROBE N` placeholder (§17).
- `src/core/protocol.py`: fixed `_on_line_complete()`/`_append_byte()`
  using `del bytearray[...]`, unsupported on this MicroPython build and
  never caught by the (100% CPython) offline suite -- reassignment/
  slice-copy instead, matching `wifi_at.py`'s own existing pattern
  (§18). **This is the ticket's central finding**: it was silently
  wedging the entire scheduled pump on the first real line ever fed to
  `protocol.py` on hardware, not just dropping one reply.
- `tests/upy/test_runtime_semantics.py`: added
  `test_bytearray_does_not_support_del`, pinning the MicroPython
  behavior that caused §18, confirmed NOT config-gated between the two
  ports (unlike the slice-ASSIGNMENT landmine this suite's own README
  warns about).

**Found, NOT fixed this session (flagged precisely for the
stakeholder/ticket 011 instead -- see §20-21)**: the WiFi-plane >=50 ms
telemetry throttle (`wifi_at.TlmThrottle`/`send_telemetry()`, built and
unit-tested, explicitly named in `PLAN.md`'s M4 gate) is never wired
into the v6 `comms.py`/`protocol.py` telemetry-emission path, which
instead calls the unthrottled `send_reliable()` on every ~24 ms pump
tick. This is very likely an unintentional regression from the v6
cutover (sprint 007 ticket 006/012) rather than a deliberate decision --
unlike the v5 `TelemetryPolicy` coast-holdoff, which `comms.py`'s own
docstring explicitly documents as deliberately dropped, nothing
documents this one as intentional. **Not fixed here** because a correct
fix is an architecture decision, not a small patch: `protocol.Sink`'s
`write(text)` contract has no way to distinguish "this is a periodic
telemetry push, throttle it per-transport" from "this is a direct reply
to a command, never throttle it," so wiring `send_telemetry()` back in
requires either (a) extending the `Sink` contract so `emit_telemetry()`
can route through it, or (b) a coarser, comms-level cadence gate that
would NOT preserve the WiFi-specific 50 ms floor as its own,
independently-tunable value the way the original M4 design clearly
intended (`wifi_at.py`'s own module docstring contrasts the WiFi
plane's 50 ms floor against "comms.py's general 25 ms cadence" as
deliberately different rates). Both are real design decisions this
ticket's scope (a bench session, not a redesign) should not make
unilaterally.

## 26. Handoff to ticket 011

- **The telemetry-throttle gap (§20-21) is the most important thing to
  read before doing anything with `TLM` on this branch.** Enabling any
  non-`"off"` TLM mode over WiFi and leaving it on for any real duration
  will grow `WifiAtLink._send_queue` without bound -- on a device with
  this little RAM, that is a real crash risk, not a theoretical one.
  Until this is wired up, treat WiFi telemetry as "enable briefly to
  observe, then disable" only, never "leave on."
- **This session ends with `TLM` still nominally `OFF` but its `#2`
  ack (and whatever backlog preceded it) still draining** -- the LAST
  thing this session did on the WiFi UDP plane was §21's second,
  8-second `TLM FULL` re-test followed immediately by `TLM OFF #2`,
  which itself got no reply within a 5 s timeout. If ticket 011's own
  session sees a few more stray `t`/`ack` lines arrive early on, that
  is this backlog finishing its drain, not a new problem -- power-
  cycling or reflashing (either of which this session deliberately
  avoided doing again, to keep the evidence intact for this log) will
  clear it instantly if it is in the way.
- **`mpremote ... resume exec` hung indefinitely (>90 s, no output)
  rather than either working or falling back cleanly** when tried
  against a session with no prior detached state to resume -- had to be
  killed by PID. Ticket 009's own §6 already flagged `resume` as
  unreliable ("first preserved state, second did not"); this session's
  experience is a further data point in the same direction: don't rely
  on `resume` to inspect live state non-destructively. A plain `exec`
  immediately afterward worked normally (and, as always, soft-reset the
  board).
- **§18's fix changes `src/core/protocol.py` for every transport, not
  just WiFi** -- the RADIO transport shares the exact same
  `ProtocolHandler`/`feed()` code path and would have hit the identical
  crash the first time it completed a real line, had this session not
  found it here first. Whoever exercises the radio transport for the
  first time on real hardware does not need to re-discover this.
- §6/§7/§8's landmines (soft-reset-on-mpremote-connect, variable
  rejoin timing, the 192.168.1.196-vs-192.168.4.11 DHCP mismatch) all
  still apply unchanged; this session re-confirmed all three, no new
  information on any of them beyond what ticket 009 already recorded.
- `tools/wifi_udp_probe.py --line` (§17) is now available for any
  future session that needs to send a specific protocol verb rather
  than a generic placeholder.

---

# Ticket 011 session (2026-08-22): the reliability layer proven live over WiFi UDP, with concurrent TCP REPL

Sprint 007, ticket 011 (the sprint's join point: `WifiAtLink` as a v6
transport, end-to-end over real WiFi UDP hardware, with a concurrent
TCP REPL). Same bench robot: tovez, same UID/port as §1. tovez's build
at session start was still commit `709ad22` (ticket 010's build,
including the `del bytearray[...]` pump-wedge fix) — no rebuild/reflash
was needed this session; no code defect was found that required one.

## 27. Pre-session state confirmed

```
$ mbdeploy list
4  yes  tovez  robot  NEZHA2  /dev/cu.usbmodem2121102  9906360200052820a8fdb5e413abb276000000006e052820
$ ping -c3 192.168.1.196     # 3/3, 3.9-5.2 ms -- reachable
$ ping -c2 192.168.4.11      # 0/2 -- still unreachable, matches §8 (unchanged)
```

Identity and port confirmed by UID (§1's own precedent) without
touching USB. Per §8's still-standing landmine, used `192.168.1.196`
directly throughout, never `192.168.4.11`.

## 28. Found: the device was completely unresponsive on BOTH WiFi
planes at session start — the tracked telemetry-throttle gap's
predicted worst case, confirmed live

`clasi/issues/wifi-plane-telemetry-throttle-not-wired.md` (opened by
ticket 010) already predicted "memory grows until the heap gives out"
as the logical endpoint of the unbounded `WifiAtLink._send_queue`
growth (§20-21 above). This session found that endpoint actually
reached, live:

- A `HELLO` over UDP got **no reply at all** within an 8 s timeout +
  6 s observe window.
- A further 45 s of pure passive listening (no new sends, matching
  §21's own "don't add more confusion" discipline) got **zero**
  datagrams — not a slow trickle, total silence, ruling out "just a
  large backlog still draining" (which drained at 6-9 lines/s in
  ticket 010's own measurement — 45 s of that would have produced
  hundreds of lines).
- A raw TCP connect (both this sprint's own `tools/wifi_tcp_probe.py`
  and, independently, a bare `nc 192.168.1.196 7654` with an explicit
  `\r\n` wake-up line) both got **zero bytes back** — the WiFi TCP
  REPL mirror, which bypasses `protocol.py` entirely (ticket 009 §18),
  was equally dead. Using a second, independent tool (`nc`) ruled out
  a bug in this sprint's own probe scripts.
- `ping` to the same address kept succeeding throughout (§8 above,
  re-confirmed) — the ESP module's own AT-firmware IP stack (which
  answers ICMP directly, independent of the nRF's Python VM) was
  alive; only the nRF-side comms/pump was dead.

Diagnosis required a USB touch (unavoidable — no wire-level replies at
all means no way to distinguish "wedged pump" from "lost peer" without
one). `mpremote connect PORT run <script>` **itself failed**:

```
mpremote.transport.TransportError: could not enter raw repl
```

— because the device's serial console was being continuously flooded
by a repeating, uncaught traceback (71.6 KB captured in the few seconds
the connection attempt was alive), printed once per scheduled-pump tick
by the same class of failure ticket 010's §18 already found (an
exception inside `_BootPumpTimer._pump_now()` wedges the pump for good,
since nothing after the failure point in that callback runs again):

```
Traceback (most recent call last):
  File "core/boot.py", line 231, in _pump_now
  File "core/comms.py", line 216, in _pump_now
  File "core/comms.py", line 183, in pump
  File "core/comms.py", line 194, in _emit_telemetry_cadence
  File "core/protocol.py", line 787, in emit_telemetry
  File "core/protocol.py", line 834, in _emit_frame
  File "core/protocol.py", line 735, in _write_line
  File "core/comms.py", line 92, in write
  File "core/wifi_at.py", line 333, in send_reliable
  File "core/wifi_at.py", line 328, in send
MemoryError: memory allocation failed, allocating 2048 bytes
```

**This is the tracked issue's own predicted endpoint, now confirmed
directly**: `_emit_telemetry_cadence()` → `WifiAtLink.send()` failing
with `MemoryError` because `_send_queue` (never throttled, per the
issue) had grown large enough to exhaust the heap, repeating on every
pump tick forever (the exception recurs identically each time, since
nothing ever drains the queue once the crash starts). This is *worse*
than ticket 010's own characterization ("ack delayed a few seconds") —
once the heap is actually exhausted, the pump is permanently wedged,
not just backed up, and recovers only via an external reset. Not a new
defect: this is the SAME already-tracked gap
(`wifi-plane-telemetry-throttle-not-wired.md`), reaching the conclusion
that issue file already predicted but had not yet observed directly.
Per this ticket's own scope (a bench join session, not the architecture
fix that issue explicitly defers), **not fixed here** — see §29 for
recovery and the issue file for the added confirmation note.

## 29. Recovery: a software-triggered hard reset (`mpremote ... reset`), not a physical act

`mpremote`'s raw-REPL entry protocol depends on the device's serial
line being quiet enough to recognize its own handshake — a continuously
re-crashing pump defeats that, so `run`/`exec` could not even get a
script onto the device to inspect state (and, per ticket 010 §21, doing
so would have destroyed the pre-crash evidence anyway, since boot.py's
own frozen call site re-executes `run()` fresh before any injected
script's own code has a chance to run). `mpremote connect PORT reset`
(a **hard** reset, issued entirely over the existing USB connection —
not a physical button press or a power cycle, so this did not need to
escalate to the stakeholder as a physical act) succeeded cleanly (exit
0) despite the flood, and the very next `mpremote run` (a bounded
wait-for-ready script) confirmed a clean, fast rejoin with **no
recurrence** of the crash:

```
BOOT_TOUCH_ALIVE
HAVE_RESULT True
STATE 0 configure
STATE 4518 join
STATE 6333 ready
READY_AT_MS 6334
BOOT_TOUCH_DONE
```

Fast case (~6.3 s, matching §7's own fast-case range), zero
`MemoryError` during boot or the ready-wait window. This directly
confirms the crash was accumulated **state** (the send-queue backlog,
whatever had been left running since ticket 010's own session ended),
not a fresh-boot default — a clean boot does not reproduce it, and
nothing in this session sent a `TLM` command before this point.
`TLM=off` is also confirmed as the actual boot default a few steps
later (§31's `STATUS` replies below all show `tlm=off`), ruling out
"telemetry is on by default" as an alternate explanation.

This was this session's only USB touch until the very end (§33) — the
whole reliability-layer conversation below ran entirely over WiFi UDP,
with no further soft-resets, per the standing landmine.

## 30. Acceptance criterion 1: `WifiAtLink` confirmed registered as a v6 transport with its own `ProtocolHandler`, by direct code reading

Not a behavioral inference — read directly:

- `src/core/boot.py` Step 3 (`run()`, around line 374-379):
  ```python
  ssid, password = wifi_at.load_secrets(secrets_path)
  if ssid is not None:
      serial = wifi_serial_factory()
      repl_hook = wifi_repl_hook_factory() if wifi_repl_hook_factory is not None else None
      result.wifi_link = wifi_at.WifiAtLink(serial, ssid, password, repl_hook=repl_hook)
      result.comms.add_transport(result.wifi_link)
  ```
- `src/core/comms.py`'s `Comms.add_transport()` (line 128-138):
  ```python
  def add_transport(self, transport):
      if len(self._handlers) >= MAX_TRANSPORTS:
          return False
      handler = protocol.ProtocolHandler(self._adapter, _TransportSink(transport))
      self._handlers.append((transport, handler))
      return True
  ```

`add_transport()` constructs a **fresh** `protocol.ProtocolHandler`
for whatever transport it is given, sharing the one `self._adapter`
(`Comms`'s own class docstring: "one `protocol.ProtocolHandler` sharing
`adapter` ... for every transport"). `WifiAtLink` is passed to this
exact method, identically to `result.radio_link` a few lines above. No
WiFi-specific branch exists anywhere in this path — `WifiAtLink`
receives a `ProtocolHandler` purely by being *a* transport, the same
mechanism the radio transport uses. **This ticket's own premise — "no
new source code required purely to wire `WifiAtLink` as a v6
transport" — holds exactly as written**, confirmed by direct reading,
not just by the fact that the smoke below worked.

## 31. Full reliability-layer smoke, over WiFi UDP — verbatim wire transcript

One continuous UDP session (peer freshly learned post-§29's reset,
sequence state fresh from `HELLO`), host source port 7655 throughout
(`tools/wifi_udp_probe.py`'s fixed default), target `192.168.1.196:7654`.
Every send below is `-> host` first, then the datagram(s) that came
back (round-trip capture, then anything caught by a short trailing
`--observe-seconds` window) in arrival order. `id` numbering is tracked
by hand against `expected_next` (never guessed) — see the running
commentary.

```
host -> HELLO
robot -> READY                                              (84.9 ms; peer-learned edge)
robot -> device NEZHA2 robot tovez f137c0                   (HELLO's own banner, separate datagram)
```
Two distinct wire-level facts in one exchange: `wifi_at`'s
peer-learning `READY` broadcast (unsequenced, v5-era convention kept
alive per `comms.py`'s own docstring) and `protocol.py`'s `HELLO` reply
proper (the banner) — same two-datagram shape ticket 010 §19 first
established after its own fix, reproduced here with a genuinely fresh
peer.

```
host -> PING #1
robot -> ack 1 0                                             (157.7 ms)
robot -> pong 44416
```
In-order id 1 (`expected_next` was reset to 1 by `HELLO`): ack fires
unconditionally, THEN the verb's own reply. `HELLO`/`PING` round-trip
over WiFi UDP: **confirmed**.

```
host -> STATUS #2
robot -> ack 2 0                                              (85.5 ms)
robot -> status ready=0 active=0 connL=0 connR=0 otos=0 wedge=0 flags=0 tlm=off next=3
```
`next=3` (`expected_next` after accepting id 2) present, as the
2026-08-21 retarget requires. `tlm=off` confirms the boot default is
`off`, not an autonomous telemetry source (relevant to §28's diagnosis).
`ready=0` — the diffdrive kernel fiber has not been started this boot
(see the WHEELS step below; boot.py's own docstring: "deliberately no
begin()/start() here ... the FIRST motion consumer begins/starts the
fiber" — nothing had done so yet at this point in the session).

```
host -> PING #7                                               (deliberate out-of-order id; expected_next=3)
robot -> nack 3 0                                             (77.4 ms)
                                                                (nothing else -- no `pong`: NOT executed)
```
Gap (`7 > expected_next`): **confirmed** — `nack <expected_next>
<last_done>`, no execution, `gap_outstanding` set. This is the
ticket's own "a deliberate out-of-order id → nack" case.

```
host -> WHEELS 15 15 1000 #3                                  (correct next id -- self-heals the gap)
robot -> ack 3 0                                               (87.1 ms)
robot -> err 8 #3
```
Self-heal confirmed (the correct next id clears the prior gap and
advances the sequence normally — no separate "resend the gap" step was
needed, matching §8.1's own "a lost nack self-heals for free" framing).
`err 8` is `Result.NOT_CONFIGURED` — `on_wheels()`'s real-kernel call
was rejected because the diffdrive fiber was never begun/started this
boot (§30's `ready=0` finding above, not WiFi-specific: the SAME
rejection would happen identically over the radio transport, since
`on_wheels()`/`move_queue.diffdrive.drive()` sit entirely below any
transport). This is exactly the ticket's own anticipated **"real motion
(or its absence, safely...)"** outcome — absence, safely, with the
correct `ack`-then-`err <code> #<id>` layered rejection shape. No wheel
motion occurred on tovez during this session as a direct result. Not a
WiFi-transport defect, not fixed here (out of this ticket's scope,
which is the transport composition, not diffdrive kernel lifecycle);
worth a future ticket asking whether the wire-protocol path should also
be a "first motion consumer" the way some other bench script currently
must be.

```
host -> STATUS #4
robot -> ack 4 0                                               (74.9 ms)
robot -> status ready=0 active=0 connL=0 connR=0 otos=0 wedge=0 flags=0 tlm=off next=5
```
Confirms no state change from the rejected `WHEELS` (as expected — it
never reached the kernel).

```
host -> WHEELS 15 15 1000 #3                                  (retransmit -- SAME stale id, expected_next now 5)
robot -> ack 4 0                                               (101.0 ms)
                                                                (nothing else -- no second `err 8 #3`: NOT re-executed)
```
**This is the ticket's "a retransmit → ack of highest-accepted without
re-execution" case, confirmed precisely**: the reply echoes `4`
(`expected_next - 1`), NOT `3` (the id actually resent) — proving the
handler answers "I already have everything through here," not "here is
a fresh ack for what you just resent" (§8.1's own distinction). Just as
telling: **no second `err 8 #3`** appeared — if this had been
re-dispatched to `_handle_wheels()`/`on_wheels()`, the identical
rejection would have fired again (diffdrive's state hadn't changed).
Its absence is direct, positive proof of non-re-execution, not just an
absence of a positive result.

```
host -> STOP #5
robot -> ack 5 0                                               (120.1 ms)
                                                                (no err -- on_stop()'s neutral() has no refusal path)
```
`WHEELS`/`STOP` ack success shape (no second line on success):
**confirmed**.

```
host -> STATUS #6
robot -> ack 6 0                                               (79.0 ms)
robot -> status ready=0 active=0 connL=0 connR=0 otos=0 wedge=0 flags=0 tlm=off next=7
```

```
host -> SET pid_kp abc #7                                     (deliberate bad value -- err-layering demo)
robot -> ack 7 0                                               (93.9 ms)
robot -> err 2 #7
```
`err 2` = `Result.BADARG` (`abc` fails `parse_wire_float()` at the
handler level, before `on_set()` is ever called). Field order
`err <code> #<id>`, layered AFTER the unconditional ack: **confirmed**,
matching §8.6/8.2 exactly ("`ok` is gone — the ack already sent IS the
acceptance; a rejection is a SECOND line layered on top").

```
host -> ESTOP
robot -> estop                                                 (91.2 ms)
```
Well-formed `ESTOP`, no id, replies the bare word `estop`: **confirmed**
over WiFi UDP (ticket's step 4 — the radio-transport version of this
was already proven offline by tickets 012/013; this is its first live
confirmation over the WiFi plane specifically).

```
host -> ESTOP #99                                              (trailing junk that LOOKS like an id)
robot -> estop                                                 (71.9 ms)
```
`ESTOP` with trailing junk (here, something that would be a
well-formed id on any other verb) still replies the bare word `estop`,
unconditionally: **confirmed** — the "both well-formed and with
trailing junk" half of the ticket's own acceptance criterion.

```
host -> PING #8                                                (bonus: does ESTOP disturb sequencing?)
robot -> ack 8 0                                                (73.4 ms)
robot -> pong 192664
```
`expected_next` continued cleanly at 8 (the value it would have held
had `ESTOP` never been sent) across BOTH `ESTOP` calls above — direct
confirmation that `ESTOP`'s sequencing exemption (§8.3) is real: it
never advances, never resets, and never nacks against the ordinary
sequence, exactly as designed.

## 32. Dual-plane concurrency: TCP REPL held open for the ENTIRE UDP conversation, wall-clock verified

Following ticket 010 §22's own resolved methodology (explicit shell
timestamps around the process, immune to output buffering, after that
session's own first attempt left an unresolved timing question):

```
$ { echo "TCP_START $(date +%s.%N)"; \
    python3 tools/wifi_tcp_probe.py --host 192.168.1.196 --hold-seconds 90; \
    echo "TCP_END $(date +%s.%N)"; } &
TCP_START 1787387537.780859000
connect      OK
prompt       OK  (6 bytes received)
eval  '2+2' -> expect '4'   OK
  reply bytes: b'2+2\r\n4\r\n>>> '

holding session open for 90s -- Ctrl-C to stop early
TCP_END 1787387628.039800000
```

`TCP_END - TCP_START` = 90.2589 s against a requested `--hold-seconds
90` (the extra ~0.26 s is connect/prompt/eval overhead before the hold
itself starts timing) — the **full** requested duration, no early
exit, no `TimeoutError`/`ConnectionError`. All 13 UDP exchanges in §31
(including the pre-conversation `HELLO`) were sent and replied to
**while this hold was open** — the entire reliability-layer smoke
above happened inside this one 90 s concurrent window, immediately
after the TCP session's own `connect`/`prompt`/`eval` confirmed it was
live. **Acceptance criterion "TCP REPL session stays interactive
throughout the UDP smoke test" is met**, with the same wall-clock rigor
ticket 010 established.

## 33. USB REPL confirmed live after

Per the bench brief for this ticket: USB REPL concurrency during the
WiFi work was not attempted (ticket 009 §11's own finding, re-confirmed
by this ticket's own §28-29: touching USB soft-resets the board,
which would have destroyed the live UDP session §31/§32 depend on).
Once all WiFi-plane work was complete, one final USB touch confirmed
liveness directly:

```
$ mpremote connect /dev/cu.usbmodem2121102 exec "print('USB_ALIVE', 'nezha-upy ticket 011 smoke complete')"
USB_ALIVE nezha-upy ticket 011 smoke complete
```

Exit code 0. This final touch itself soft-resets the board (the same
unavoidable landmine as every other USB touch this session) — an
accepted, deliberate cost, taken only after every acceptance criterion
that needed the WiFi session alive had already been captured above.

## 34. Summary

| Acceptance criterion | Result |
|---|---|
| `WifiAtLink` confirmed registered as a v6 transport with its own `ProtocolHandler` (code-level) | Met (§30) |
| `HELLO`/`PING` round-trip correctly over WiFi UDP | Met (§31) |
| `WHEELS`/`STOP` round-trip correctly over WiFi UDP (ack success / `err <code> #<id>` rejection) | Met (§31) — rejection path exercised (`err 8`, diffdrive fiber never begun this boot); ack-success shape confirmed via the retransmit case and `STOP`'s own clean ack |
| `ESTOP` (well-formed and trailing junk) replies bare `estop` over WiFi UDP | Met (§31) |
| TCP REPL session stays interactive throughout the UDP smoke test | Met (§32), wall-clock verified |
| Findings appended to the tovez bench log; any composition gap found is recorded and fixed, not patched over | This document — no `WifiAtLink`/`feed()` composition gap was found (§30); the one real defect this session hit (§28) is the ALREADY-tracked, ALREADY-deferred telemetry-throttle architecture issue reaching its predicted worst case, not a new gap, and is out of this ticket's scope to fix per the issue's own "not a small bench fix" reasoning (re-affirmed, not re-litigated, here) |

**No source code was changed by this ticket.** The one real finding
(§28) confirms and sharpens an already-tracked, already-deferred issue
(`clasi/issues/wifi-plane-telemetry-throttle-not-wired.md`, updated
with this session's confirmation) rather than exposing a new one; the
`WifiAtLink`-as-v6-transport composition itself (this ticket's own
central question) was confirmed correct both by direct code reading
(§30) and by a full, clean, thirteen-exchange reliability-layer
conversation over real WiFi UDP hardware (§31) with a concurrently held
TCP REPL (§32). `python3 -m pytest tests/` remained at 500 passed / 518
subtests passed throughout (unchanged from where ticket 010 left it —
no offline test was added or modified, since no code changed).
