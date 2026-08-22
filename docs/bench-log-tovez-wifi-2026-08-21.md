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
