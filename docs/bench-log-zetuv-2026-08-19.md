# Bench log: zetuv, 2026-08-19

Sprint 002, ticket 001 (`clasi/sprints/002-zetuv-bench-square-tour-wheels-demo/tickets/001-zetuv-config-flash-repl-wiring-verification.md`).
Hardware execution performed directly by the programmer agent, per direct
stakeholder directive (unlike sprint 001, where all hardware steps were
deferred). This is the **first time** this repo's image has been flashed
to real hardware, and the first time `docs/bench-acceptance-procedures.md`'s
own A.2/A.4 procedures have been exercised on a real micro:bit rather than
written speculatively — two findings below (the filesystem-size limit and
the combined-drive anomaly) are new information this session surfaced,
not previously known.

All commands below were run from the repo root
(`/Volumes/Proj/proj/RobotProjects/nezha-upy`) against the physical
device at `/dev/cu.usbmodem2121202`.

## 1. Fleet check (deploy-target discipline)

```
$ mbdeploy list
```
Confirmed at the start of this session: `getez` (`/dev/cu.usbmodem214102`,
UID `990636020005282017449eac613c0332000000006e052820`), `zetuv`
(`/dev/cu.usbmodem2121202`, UID
`9906360200052820312bde85515a72e6000000006e052820`), `zavaz`
(`/dev/cu.usbmodem2121302`, UID
`9906360200052820e9d16c3809a44554000000006e052820`) all connected.

```
$ mbdeploy probe
```
Populated the registry with live role reads: **`getez` = `RADIOBRIDGE`
relay, `zavaz` = `RADIOBRIDGE` relay, `zetuv` = `NEZHA2` robot** (enum 2).
Confirms both non-zetuv boards on this bench are relay-class — neither
was targeted, and `--force-relay` was never passed, at any point in this
session.

## 2. Build

```
$ ./build.sh --clean --with-diffdrive --with-wifi
```
Note: an earlier `./build.sh --help` in this session was NOT a no-op —
`build.sh` has no `--help` handling, so that invocation silently ran a
plain, non-`--clean`, no-diffdrive/no-wifi build (caught before any
hardware step; discarded by re-running the correct invocation above in
the background and waiting for it to complete). Recorded here as a
process note, not a hardware finding.

Result: succeeded. Tail output:

```
arm-none-eabi-size ../lib/codal/build/MICROBIT
   text	   data	    bss	    dec	    hex	filename
 335852	      8	 126992	 462852	  71004	../lib/codal/build/MICROBIT
...
SoftDevice    none (DEVICE_BLE=0, no-SoftDevice link)
MicroPython   0x00000..0x51fec
Layout table  0x52fd0..0x53000
Filesystem    0x6d000..0x73000

=== Done ===
Hex ready.
```

Flash end (`0x51fec`) is well under `_fs_start` (`0x6D000`), matching the
build gate's own invariant. `text=335852` is larger than ticket 007's
recorded M5 baseline (`text=333212`, that build's own `--with-wifi` was
not part of the baseline configuration) — consistent with this build
additionally including the wifiuart native module; not itself compared
against a same-flag baseline this session (no such baseline is recorded
in this repo yet).

## 3. Deploy (by UID only)

```
$ mbdeploy deploy 9906360200052820312bde85515a72e6000000006e052820 \
    --hex micropython-microbit-v2/src/MICROBIT.hex
```

Target: **zetuv's UID only**, confirmed against the fresh `mbdeploy list`/
`probe` output above immediately before deploying. `--force-relay` never
passed; getez/zavaz never named as a deploy target at any point.

Result: initial `pyocd flash` failed with `flash erase sector failure
(address 0x00000000; result code 0x67)` — the documented "locked/
protected device" case (`mbdeploy --agent` §6.5). `mbdeploy` then ran its
own automatic CTRL-AP mass-erase recovery and retried, which succeeded:
`Erased 340992 bytes (84 sectors), programmed 340992 bytes (84 pages),
identical 0 bytes (0 pages) at 15.33 kB/s`. **Exit code 0.** This
recovery path is documented, automatic `mbdeploy` behavior, not a
manual workaround applied here.

Waited **5 s** (`sleep 5`) before opening a REPL, per bench convention.

## 4. REPL smoke test

```
$ mpremote connect /dev/cu.usbmodem2121202 exec "print('hello'); import diffdrive; print('diffdrive', diffdrive)"
hello
diffdrive <module 'diffdrive'>
```

REPL answered; `diffdrive` importable. Before any config is present:

```
lastError before configure: refused_unconfigured
output before configure: {}
```

Matches the documented fail-closed contract (native module present and
reachable, refuses every drive call with no `configure()` yet called).

**Not independently captured this session**: the wire-level
`DEVICE:NEZHA2:robot:...` banner / `READY` text. `comms.Comms.send_banner()`/
`send_ready()` broadcast only to *registered transports* (radio, WiFi) —
`src/comms.py`'s `_broadcast_reliable()` — not to the raw USB REPL stdout,
so there is no banner text to observe from a plain `mpremote` session
without a radio relay listening. This is expected behavior (grounded in
the source, not a gap in this bench pass) but flagged since the ticket
names "banner ... answers" as evidence to record.

## 5. Copying `zetuv.json` onto the device — filesystem-size finding

```
$ mpremote connect /dev/cu.usbmodem2121202 fs cp data/zetuv.json :robot.json
mpremote: cp: robot.json: No space left on device.
```

**New finding this session** (previously untested on real hardware): the
repo's fully-annotated `data/zetuv.json` (20,484 bytes, matching this
fleet's convention of carrying extensive `_note` provenance/history text
in every group) does **not fit** the device's on-flash filesystem. The
build's own layout table (§2 above) gives the filesystem region as
`0x6d000..0x73000` = 24,576 bytes total, before any per-file/block
overhead the microbit filesystem driver itself imposes — so the actual
usable budget is smaller still. This was previously undemonstrated:
`docs/bench-acceptance-procedures.md` A.2 instructs copying `tovez.json`
(59,632 bytes!) onto a device the same way, which — per this same
arithmetic — would fail identically; that step had never actually been
run on hardware before this ticket (sprint 001 deferred every hardware
step; this is the first).

**Resolution applied**: config.py treats every `_`-prefixed key as
free-text documentation it ignores (`data/README.md`'s own established
convention). A stripped copy — every `_`-prefixed key removed, compact
JSON — was generated and copied instead:

```
$ python3 -c "... strip '_'-prefixed keys, json.dumps(..., separators=(',', ':')) ..."
stripped compact bytes: 2413
$ mpremote connect /dev/cu.usbmodem2121202 fs cp <stripped-file> :robot.json
$ mpremote connect /dev/cu.usbmodem2121202 exec "print(len(open('robot.json').read()))"
2413
```

Succeeded. **The repo's `data/zetuv.json` remains the full, documented
source of truth** — this stripping is a device-flash-time transform only,
not a change to what's checked in. This filesystem-size constraint is
worth flagging to whoever picks up ticket 002 or any future ticket that
copies one of this fleet's more heavily-annotated robot JSONs (e.g.
`tovez.json`) onto real hardware — none of them will fit unstripped.

## 6. Boot-time config load — confirmed fail-closed (expected, in-scope)

After copying `robot.json` and a hardware reset (`mpremote ... reset` +
5 s settle):

```
post-reset lastError: refused_unconfigured
post-reset output: {}
```

**Expected, not a bug**: `data/zetuv.json`'s `motors` group deliberately
does not carry `travel_calib_left`/`travel_calib_right` — sprint.md's own
Out of Scope section: "zetuv.json stays a no-calibration profile this
sprint, same tier as its `tovez_nocal.json` template," and that template
itself ships without those two fields. `config.REQUIRED_KEYS` requires
both, so `config.load_robot_config()` fail-closes
(`ConfigError: missing travel_calib_left`) exactly as it already would on
`tovez_nocal.json` itself — `boot.py`'s documented fail-closed path
(banner/READY/`diffdrive` import still available; motion refused). This
is why wiring verification below is done via direct REPL
`diffdrive.configure()` calls that bypass `boot.py`/`config.py` entirely,
matching `docs/bench-acceptance-procedures.md` A.4's own documented use
of the manual path. **Flagged for ticket 002**: the on-device
auto-boot-configure path will not activate for zetuv until/unless a
travel_calib pair (or some other resolution) is added — out of this
ticket's scope to add (calibration is explicitly excluded), but ticket
002's demo will need to drive `diffdrive` directly rather than relying on
boot's automatic `RobotDispatch` wiring, matching sprint.md's own
Architecture note that the programmer implementing ticket 002 should
ground the demo's approach in what `motion.py` actually supports.

## 7. Wiring verification (smallest-visible-pulse, one wheel at a time)

All driven via `mpremote connect /dev/cu.usbmodem2121202 run <script>.py`
(a *single* mpremote invocation per script — see the process note below on
why). Encoder deltas (`diffdrive.output()`'s `positionLeft`/`positionRight`)
are the observational evidence throughout, per this ticket's own
instruction ("encoder deltas are the ground truth, not which wheel looks
like it should be left") — **this agent has no camera/vision access to
the physical bench**, so this is also the only observational channel
available, not merely the preferred one.

**Process note**: a separate `mpremote connect PORT exec "..."` per step
was tried first and found to **reset the board between invocations**
(each fresh `exec` call re-enters raw REPL mode, which re-triggers the
boot sequence — confirmed directly: a `diffdrive.configure()` done in one
`exec` call was gone, `lastError()` back to `refused_unconfigured`, in the
very next separate `exec` call). All of §7's actual measurements were
therefore done as one Python script per `mpremote run`, keeping
`configure()`/`begin()`/`start()` and every probe in the same live session
— `configure()` is documented single-call-scoped (`native/moddiffdrive.cpp`:
a second call re-placement-news over the same storage while a fiber from
an earlier `start()` may still be live), so each *new* configuration used
a fresh `mpremote run` (which power-on-resets the board), never a second
in-session `configure()` call on top of an already-started kernel.

### 7a. Baseline configure (ports 1 & 2, identity signs — matching this
fleet's own established port pair, tested rather than assumed)

```python
diffdrive.configure(left_port=2, right_port=1, fwd_sign_left=1, fwd_sign_right=1,
                     max_duty=0.15, full_duty_velocity=0.0, cycle_period_ms=24)
diffdrive.begin(); diffdrive.start()
```
`configure`/`begin`/`start` all returned `"ok"`. `output()` after ~100 ms:
`connectedLeft: True, connectedRight: True` (both ports ack on the I2C
bus), `cycleCount` advancing (kernel fiber alive), `cyclePeriodMeasured`
~28 ms (close to the configured 24 ms cadence).

### 7b. LEFT (port 2) alone, low duty — `driveDuty(0.06, 0.0, 300)`

`positionLeft`: 0.0 (baseline) → 0.0 (mid-pulse) → 0.0 (post-lease) → 0.0
(stop-verify +2 s). **No movement at 0.06 duty.**

### 7c. LEFT (port 2) alone, higher duty — `driveDuty(0.20, 0.0, 400)`

`positionLeft`: 0.0 → 2.0 (mid-pulse, `velocityLeft` 71.3) → 5.0
(post-lease) → 5.0 (stop-verify +2 s, no further drift). **Port 2 moves,
positive duty → positive position** — 0.06 duty was simply below this
wheel's breakaway threshold; 0.20 was not.

### 7d. RIGHT (port 1) alone, low duty — `driveDuty(0.0, 0.06, 300)`

`positionRight`: 0.0 → 11.0 (mid-pulse, `velocityRight` present) → 61.0
(post-lease) → 61.0 (stop-verify +2 s, no drift). **Port 1 moves easily
even at low duty, positive duty → positive position.**

### Determination

| Field | Measured value | Basis |
|---|---|---|
| `left_port` | 2 | port 2, driven alone, produces real encoder motion (§7c) |
| `right_port` | 1 | port 1, driven alone, produces real encoder motion (§7d), and is markedly more free-spinning than port 2 |
| `fwd_sign_left` | 1 | positive duty on port 2 alone → positive `positionLeft` at identity sign, so no correction needed |
| `fwd_sign_right` | 1 | positive duty on port 1 alone → positive `positionRight` at identity sign, so no correction needed |

Both signs came out **identity** (+1/+1) — different from tovez.json's
own (-1/+1) and gopiv.json's (+1/-1) opposite-pair fixes. Not assumed to
match either; independently derived from zetuv's own pulses. Left/right
**port** values (2/1) do match this fleet's established convention — not
re-derived from a fresh visual check (no camera available to this
agent), flagged as convention-matched, not independently visually
re-verified, in `data/zetuv.json`'s own `_port_note`.

## 8. Combined-drive anomaly (new finding, flagged, not resolved)

With **both** wheels driven simultaneously, port 2 (left) did not move at
all in either of two trials, while port 1 (right) moved briskly:

- `driveDuty(0.20, 0.20, 1000)`: `positionRight` 0 → 86 (mid, 300 ms) → 500
  (post-lease); `positionLeft` stayed **0.0 throughout**, despite
  `appliedDutyLeft` reading nonzero (duty was being commanded).
- Follow-up diagnostic, asymmetric duty to rule out a shared-current
  explanation — `driveDuty(0.25, 0.06, 500)` (left driven *harder* than
  right this time): `positionRight` 0 → 105 → 297; `positionLeft` again
  **0.0 throughout**. Raising left's own duty relative to right's did not
  help, ruling out simple current-sharing/voltage-sag as the explanation.

**Not root-caused this ticket** — deliberately not chased further, to
avoid stressing the drivetrain beyond the smallest-necessary probing
(this ticket's own discipline: "one wheel at a time when probing").
Candidates, none confirmed: a real electrical/mechanical fault specific
to simultaneous 2-channel drive on this unit, an I2C bus timing/ordering
issue under combined traffic, or (unverifiable without a camera) a
telemetry-read glitch where the wheel does move but `positionLeft` isn't
updating correctly under combined traffic. **Flagged prominently for
ticket 002**, which needs both wheels moving together to demonstrate a
square path and will hit this directly.

The safety-critical property was unaffected by this anomaly and held
correctly in every trial (see §9).

## 9. Safety spot-check (lease expiry)

Using the `driveDuty(0.20, 0.20, 1000)` trial from §8 (a combined,
~1000 ms lease, as the ticket's own spot-check calls for):

| Reading | `leaseExpired` | `appliedDutyLeft` | `appliedDutyRight` | `positionRight` |
|---|---|---|---|---|
| mid-pulse (T+300 ms) | False | 3.0 | 3.0 | 86.0 |
| post-lease (T+1.1 s) | **True** | **0.0** | **0.0** | 500.0 |
| stop-verify (T+2.1 s) | True | 0.0 | 0.0 | 500.0 (unchanged) |
| stop-verify (T+3.1 s) | True | 0.0 | 0.0 | 500.0 (unchanged) |

**Result: PASS.** Duty zeroed at lease expiry in every trial run this
session (§7b–§8 as well), and position held exactly steady (Δposition = 0
for both wheels) across the following 2 s stop-verify window every time —
no drift, no re-latching. This held true independent of the §8 anomaly.

## 10. Device left in a clean state

```
$ mpremote connect /dev/cu.usbmodem2121202 reset
$ sleep 5
$ mpremote connect /dev/cu.usbmodem2121202 exec "..."
post-reset lastError: refused_unconfigured
post-reset output: {}
files: ['robot.json']
```

Idle, unconfigured (expected — see §6), `robot.json` present on the
filesystem with the final measured wiring values. No motion commanded at
end of session.

## 11. Offline gate

```
$ python3 -m pytest tests/ -q
195 passed, 518 subtests passed in 0.44s
```

193 baseline (sprint 001) + this ticket's own `TestZetuvRadioChannel` and
`TestZetuvWiring` additions to `tests/test_robot_config_data.py`. Green.

## Summary for ticket 002 / future readers

1. `data/zetuv.json` exists, derived from `tovez_nocal.json`, with
   `left_port=2`/`right_port=1`/`fwd_sign_left=1`/`fwd_sign_right=1`
   bench-measured on zetuv itself (§7).
2. **Filesystem-size limit**: a fully-annotated robot JSON does not fit
   this port's on-device filesystem; strip `_`-prefixed keys before
   copying any of this fleet's JSON files to a real device (§5).
3. **Combined-drive anomaly, unresolved**: driving both wheels together
   currently does not move the left wheel (port 2) at all, regardless of
   relative duty — needs investigation before ticket 002's square tour
   can be expected to work as-is (§8).
4. **Boot auto-configure will not activate** for zetuv as shipped (no
   `travel_calib_left`/`right` — an intentional no-cal scope decision);
   ticket 002 will need to drive `diffdrive` directly (§6).
5. Safety spot-check (lease-expiry zeroing) passed cleanly every time
   (§9).

---

# Ticket 002 session: combined-drive anomaly root-cause + square tour demo

Sprint 002, ticket 002
(`clasi/sprints/002-zetuv-bench-square-tour-wheels-demo/tickets/
002-on-device-square-tour-demo.md`). Continues directly from ticket
001's session above, same date, same physical device
(`/dev/cu.usbmodem2121202`, UID
`9906360200052820312bde85515a72e6000000006e052820`). `mbdeploy list`/
`mbdeploy probe` re-confirmed at the start of this session and again
before every deploy step below: getez/zavaz both still RADIOBRIDGE
relays, never targeted, `--force-relay` never passed.

## 12. Pre-existing blocker: raw-REPL access lost (new finding, resolved)

Before any of ticket 001's own findings could be re-checked, the very
first `mpremote ... run` invocation this session failed with
`TransportError: could not enter raw repl`, and the device's USB
serial line was found to be continuously emitting `TLM:0:0:0\n` (bare
`pyserial` read, bypassing `mpremote` entirely, confirmed this was
real repeating text, not line noise). No literal `"TLM:0:0:0"` string
exists anywhere in this repo's own source (`grep`-searched
exhaustively across `src/`, `native/`, `vendor/`, `reference/`) — the
exact origin was **not identified**. `mbdeploy probe`'s own
`config/devices.json` registry shows it can read a live
`DEVICE:NEZHA2:robot:zetuv:...`-style announcement from this same
serial line, which is itself a fact not fully reconciled with ticket
001's own claim that `comms.py`'s broadcast methods never reach raw
USB stdout — flagged here as an open question for whoever next
touches the comms/transport wiring, not resolved this ticket.

**Recovery attempts, in order**: Ctrl-C over raw serial (no effect —
the spew continued unbroken); Ctrl-C + Ctrl-A raw-repl entry sequence
sent directly over `pyserial` (no raw-repl prompt ever appeared);
`mpremote ... reset` (failed the same `ensure_raw_repl()` way — its
own reset command apparently also depends on raw-repl entry, so it
likely never reached the board); a genuine hardware reset via the
on-board debug probe, bypassing serial entirely
(`pyocd reset -u 9906360200052820312bde85515a72e6000000006e052820`,
exit 0) — the SAME `TLM:0:0:0` spew reappeared immediately after a
~5 s settle, which rules out leftover interactive REPL state (a real
probe-level reset clears that) and points instead at something that
happens fresh on every boot. **What worked**: a full re-deploy of the
already-built, unchanged hex (`mbdeploy deploy
9906360200052820312bde85515a72e6000000006e052820 --hex
micropython-microbit-v2/src/MICROBIT.hex` — no rebuild, native/vendor
untouched) — this hit the SAME locked-device `flash erase sector
failure (result code 0x67)` ticket 001's own initial deploy hit, and
`mbdeploy`'s automatic CTRL-AP mass-erase recovery cleared it exactly
as documented (§3 above). After the mass erase + reflash, the serial
line was silent (confirmed via bare `pyserial` read) and
`mpremote ... exec "import diffdrive"` worked cleanly again.

**Consequence**: the mass erase wipes the on-device filesystem, so
`/robot.json` was re-copied (same stripped/compact approach as §5
above — 2413 bytes, byte-identical procedure) before any further work.
**Not root-caused, workaround applied and disclosed honestly**: this
is exactly the kind of thing this ticket's own instructions warn
against papering over silently — recorded here as an open finding, not
claimed as understood. It does not appear to be the SAME phenomenon as
§13 below (that one reproduces on demand from a clean boot every time;
this one has not recurred since the reflash, through two full demo
runs and multiple diagnostic sessions).

## 13. Combined-drive anomaly — root-caused and resolved

**Approach** (systematic-debugging discipline, per this ticket's own
instruction): reproduce first, discriminate hypotheses with the
cheapest probe before any fix attempt, cap at ~4 distinct attempts.

**Attempt 1 — reproduce, then test staggered engagement.** A bench
script (`configure(max_duty=0.15, ...)`, matching ticket 001's own
convention exactly) reproduced ticket 001's finding once more:
`driveDuty(0.20, 0.20, 400)` left `positionLeft` at 0.0 throughout,
`positionRight` climbing normally. The leading hypothesis going in was
(a) an I2C write-collision between the two channels' near-simultaneous
duty writes in one kernel cycle (both channels share the SAME 7-bit
I2C address 0x10 — only the `port` byte in the write frame
discriminates the channel — read closely in `vendor/nezha_motor.cpp`/
`native/i2c_broker.cpp` before forming this hypothesis, not assumed).
Test: stagger the engagement — `driveDuty(0.20, 0.0, 500)` (left
alone, let it establish) then `driveDuty(0.20, 0.20, 600)` (bring
right in after, which triggers only a right-channel write since
left's own commanded duty did not change — the write-on-change dedup
in `NezhaMotor::writeRawDuty()`). **Result: LEFT DID NOT MOVE EVEN
WHEN DRIVEN ALONE, FIRST, WITH NO RIGHT-WHEEL TRAFFIC AT ALL** — this
directly refutes hypothesis (a): there was no second channel present
to collide with. Reversing the stagger order (right first, then bring
left in) gave the identical result. Two attempts, hypothesis (a)
refuted with the cheapest available discriminating evidence (single-
channel reproduction).

**Attempt 2 — units hypothesis.** Reading the vendored kernel's own
`Config`/`Command`/`Output` struct field comments closely
(`vendor/differential_drive.h`) shows `maxDuty`, `dutyLeft`,
`dutyRight`, `appliedDutyLeft`/`Right` are ALL annotated `// [%]`
(percent, 0-100) — consistently, throughout the whole struct — not the
`[-1,1]` fraction `native/moddiffdrive.cpp`'s own file-header comment
and `native/README.md` both (independently) claimed. Tracing the
actual math in `DifferentialDrive::controlStep()`'s raw-duty branch
confirms it: `demandL = cmd.dutyLeft * 0.01f` (a percent-to-fraction
conversion) clamped against `rail = active_.maxDuty * 0.01f`. With
`max_duty=0.15` (intended as "15%"), the REAL rail is `0.15 * 0.01 =
0.0015` (0.15%) — and ANY nonzero duty clamped into that rail gets
BOOSTED back up to `NezhaMotor`'s own 3% output-deadband floor
(`writeShapedDuty()`: a sub-deadband nonzero duty is boosted to the
deadband, sign-preserving, never zeroed) — so every commanded duty,
regardless of the number requested, collapsed to the SAME ~3% floor.
Bench evidence this ticket's own §7c/§7d matched: 3%-floor duty was
right at LEFT (port 2)'s own breakaway threshold — occasionally just
enough (ticket 001's lone single-wheel test moved 5 ticks), usually
not (every combined trial in ticket 001 AND every reproduction this
ticket, alone or combined, moved 0 ticks). RIGHT (port 1)'s much lower
breakaway threshold meant the SAME 3% floor moved it reliably every
single time in both tickets — which is exactly why this read as a
"combined-drive-specific, left-only" fault: it was a marginal-duty
reliability issue that happened to always show up as "left doesn't
move," not a combined-vs-single-channel effect at all.

**Verification** (the actual fix, bench-run):
`diffdrive.configure(..., max_duty=25.0, ...)` (a genuine 25% rail)
followed by `driveDuty(20.0, 0.0, 400)` (left alone),
`driveDuty(0.0, 20.0, 400)` (right alone), and
`driveDuty(20.0, 20.0, 400)` (combined, simultaneous) — **all three
moved both wheels reliably**, with clean stop-verify (Δposition = 0
over 1 s after each `neutral()`) between every trial:

```
left-alone-mid   posL 222.0 posR 0.0    appL 20.0 appR 0.0
left-alone-postlease posL 717.0 posR 0.0
right-alone-mid  posL 795.0 posR 334.0  appL 0.0  appR 20.0
right-alone-postlease posL 795.0 posR 917.0
combined-mid     posL 1070.0 posR 1303.0 appL 20.0 appR 20.0
combined-postlease posL 1600.0 posR 1906.0
combined result left_moved True right_moved True
```

**Root cause, stated plainly**: a call-site UNITS bug (percent vs.
fraction), not an I2C timing/collision issue, not a vendor-side
kernel fault, not a power/brownout effect, not a watchdog/lease
interaction. `driveDuty`/`configure`'s own documented `[-1,1]` units
in `native/moddiffdrive.cpp`'s file header and `native/README.md`
were themselves wrong relative to what the vendored kernel actually
implements — fixed in both files this ticket (doc-only, no rebuild
needed — see the diff), and in `docs/bench-acceptance-procedures.md`'s
own A.4 worked example (`max_duty=0.15`/`driveDuty(0.05, 0.05, ...)`
corrected to `15.0`/`driveDuty(5.0, 5.0, ...)`, not independently
re-verified on tovez's own hardware this session but the same
convention bug applies to any caller of this same binding).
`data/zetuv.json`'s own `_combined_drive_anomaly_note` is updated to
match. **No workaround was needed** — this is a genuine root-cause
fix, not a papered-over symptom: the demo below uses the corrected
percent convention throughout, with no staggering, alternating, or
other engagement trick.

## 14. Duty sweep — choosing the demo's operating point

A follow-up sweep (`max_duty=25.0` rail, `driveDuty(d, d, 500)` for
`d` in `[6.0, 8.0, 10.0]`, reading `velocityLeft`/`velocityRight`
directly) found this plant is close to on/off around breakaway: even
6% duty already produces ~480-680 mm/s of measured wheel speed
(`velocityLeft` 679.7, `velocityRight` 963.7 counts/s at
`ticks_per_mm=1.4187` from `data/zetuv.json`'s own — inherited,
unverified — wheels block). sprint.md's own `omega_max=2.4 rad/s`
ceiling (carried from radio-robot-elite's closed-loop `TOUR_SQUARE`
planner) implies a wheel tangential speed of only ~150 mm/s at this
robot's 128 mm trackwidth — 3-4x below what even the gentlest reliable
duty produces. `driveDuty()` is open-loop raw PWM with no velocity
feedback, so there is no dial that reaches that target without either
a real calibrated velocity loop (out of this sprint's own no-cal
scope) or the drive block's disabled `crawl_pulse` dithering (its own
calibration exercise). **Disclosed, not silently missed**:
`SEGMENT_DUTY_PERCENT = 6.0` (the gentlest bench-verified-reliable
value) is what `src/demo_square.py` uses; `omega_max` is not met, and
this is documented in the module's own docstring and here rather than
claimed as satisfied.

## 15. Square tour demo — implementation and bench run

> **CORRECTION (2026-08-19, sprint 004 ticket 001,
> `clasi/sprints/004-square-tour-travel-units-fix/`)**: the "500 mm"
> legs documented in this section were never actually 500 mm of real
> travel — `TICKS_PER_MM` (1.4187) was derived from unverified
> template wheel/tick constants, off by a factor of ~4.2-5.3x. The
> `target 709.35`/`142.62` tick counts below are the OLD, WRONG
> targets. See the "Sprint 004 ticket 001" section at the end of this
> file for the root cause, the fix, and the re-verification attempt.
> This entry is left unedited below, per that ticket's own instruction
> not to silently rewrite history.

**Implementation choice** (full reasoning in `src/demo_square.py`'s
own module docstring): direct, timed, encoder-terminated
`diffdrive.driveDuty()` calls for EVERY segment (legs and pivots
alike) — not `motion.MoveQueue`. `MoveQueue.tick()` drives every move
through `diffdrive.drive()` (VELOCITY mode), which the vendored kernel
refuses outright whenever `fullDutyVelocity <= 0`
(`Status::kRefusedUnconfigured`'s own doc comment: "VELOCITY with
fullDutyVelocity == 0") — and zetuv's own config deliberately carries
no `travel_calib_left`/`right` this sprint, so there is no real number
to derive `full_duty_velocity` from without fabricating a calibration
sprint.md's own Design Rationale explicitly rejects. `driveDuty()`
needs no `fullDutyVelocity` at all (the vendored kernel's own comment:
"usable for plant-ID runs on an uncalibrated robot") — the module uses
it uniformly, terminating each segment by polling
`diffdrive.output()`'s position fields against a target tick count
(mean of `|Δleft|`/`|Δright|`, mirroring
`MoveQueue._distance_travelled()`'s own convention) rather than a
blind timer, with a hard safety timeout (3000 ms) per segment.

**Run command** (one line, matches the module's own docstring):

```
mpremote connect /dev/cu.usbmodem2121202 run src/demo_square.py
```

**Run 1**:

```
demo_square: segment 0 leg   target 709.35 dLeft 709.0 dRight 742.0 mean 725.5 reached True elapsed 900
demo_square: segment 1 pivot target 142.62 dLeft -111.0 dRight 236.0 mean 173.5 reached True elapsed 350
demo_square: segment 2 leg   target 709.35 dLeft 683.0 dRight 755.0 mean 719.0 reached True elapsed 950
demo_square: segment 3 pivot target 142.62 dLeft -75.0  dRight 217.0 mean 146.0 reached True elapsed 300
demo_square: segment 4 leg   target 709.35 dLeft 650.0 dRight 811.0 mean 730.5 reached True elapsed 900
demo_square: segment 5 pivot target 142.62 dLeft -66.0  dRight 222.0 mean 144.0 reached True elapsed 300
demo_square: segment 6 leg   target 709.35 dLeft 706.0 dRight 795.0 mean 750.5 reached True elapsed 950
demo_square: segment 7 pivot target 142.62 dLeft -97.0  dRight 200.0 mean 148.5 reached True elapsed 300
demo_square: tour complete
```

**Run 2** (repeated to confirm this was not a fluke, same command,
fresh boot): all 8 segments again `reached True`, comparable
magnitudes/timing (leg deltas 663-784 per wheel, pivot deltas
-78..-117 left / 200-222 right). Both runs exited 0.

**Observation, plainly stated**: the wheels visibly execute a
square-ish tour — 4 legs, 4 left (CCW) pivots, rest-to-rest with a
1.2 s settle between every segment, every segment's encoder evidence
showing real, correctly-signed motion (pivots: negative `Δleft`,
positive `Δright`, matching the kernel's own CCW-positive `twist`
convention). Not survey-grade: RIGHT consistently outpaces LEFT on
every leg (e.g. run 1's legs: 650-709 left vs. 742-811 right) and
over-rotates on every pivot (e.g. run 1: 66-111 left vs. 200-236
right) — the same per-wheel breakaway/response asymmetry this whole
investigation surfaced (port 1/right is a notably freer-spinning wheel
than port 2/left on this unit). This means the real path drifts
somewhat rather than tracing a geometrically perfect square — expected
and acceptable per this ticket's own acceptance criteria ("uncalibrated
... square-ish", not precision-verified). No camera/vision access was
available to this agent this session either, so "wheels visibly move"
is evidenced here by encoder deltas exactly as ticket 001's own wiring
verification was — the only observational channel available.

**Post-run device state**: `diffdrive.neutral()` is the module's own
last hardware call before `run()` returns (see `src/demo_square.py`).
A separate `mpremote ... exec` after a `run()` session is a NEW raw-
repl session (this port's own soft-reset-on-raw-repl-entry behaviour,
matching ticket 001's own §7 process note) — so a stop-verify via a
second `exec` call is not meaningful here; instead, REPL health was
confirmed post-run (`import diffdrive` succeeds, `lastError()` reports
`refused_unconfigured` — the expected fail-closed state of a fresh,
unconfigured boot, exactly matching every prior session's own final
state).

## 16. Offline gate

```
$ python3 -m pytest tests/ -q
204 passed, 518 subtests passed
```
195 (ticket 001 baseline) + 9 new `tests/test_demo_square.py` cases
covering `build_square_tour()`'s pure segment-generation logic (shape,
signs, tick-target arithmetic, parametrization) — the hardware-facing
half (`run()`/`_run_segment()`) is not unit-testable without asserting
something about timing this module never promises, per that test
file's own docstring; verified on the bench instead (§15 above).
`python3 -m py_compile src/demo_square.py` and
`mpy-cross src/demo_square.py -o ...` both clean.
`git diff --exit-code -- vendor/` clean — vendor/ untouched.
`native/` also untouched (only `native/README.md`, a doc file, and
`data/zetuv.json`'s note were edited alongside `src/demo_square.py`
and `tests/test_demo_square.py`).

`manifest.py` deliberately does NOT list `demo_square.py` — it is a
bench demo script that drives motors as a side effect of being
imported, not a framework module; freezing it would make a bare
`import demo_square` from any REPL an accidental motor-drive trigger.
`tests/test_manifest_freeze.py` was extended with a narrow, named
`_BENCH_ONLY_MODULES` exclusion (documented in that file's own
docstring) rather than weakened generally — the invariant still holds
for every framework module.

## Summary for future readers

1. **Combined-drive anomaly: root-caused, resolved, no workaround
   needed.** It was a `max_duty`/`driveDuty` PERCENT-vs-fraction units
   bug in how `diffdrive.configure()` was being called (ticket 001's
   own `max_duty=0.15` convention, inherited from
   `docs/bench-acceptance-procedures.md`'s own A.4 example) — not an
   I2C timing issue, not a vendor/native code fault, not power/
   brownout, not watchdog/lease interaction. Both wheels drive
   reliably, alone and simultaneously, once `max_duty`/`dutyLeft`/
   `dutyRight` are passed as real percent values (0-100).
2. `native/moddiffdrive.cpp`'s file header, `native/README.md`, and
   `docs/bench-acceptance-procedures.md`'s A.4 example were all
   corrected to state/use the real `[%]` convention.
3. `src/demo_square.py` drives the full 8-segment square tour via
   direct, encoder-terminated `diffdrive.driveDuty()` calls (not
   `motion.MoveQueue`, which needs calibration zetuv deliberately does
   not have) — run twice on zetuv, both runs completed all 8 segments
   with real, correctly-signed encoder motion.
4. `omega_max=2.4 rad/s` is NOT met and is disclosed as such — this
   plant's breakaway-to-reliable-speed jump is too steep for raw duty
   control to hit that ceiling without a real velocity loop.
5. A separate, unrelated, NOT-root-caused finding this session: a
   `TLM:0:0:0` USB-serial spew appeared before any of this ticket's
   own probing began, blocking raw-REPL access; a hardware reset via
   the debug probe did not clear it, but a full reflash of the
   already-built hex did (§12). Flagged for whoever next investigates
   the comms/transport wiring — not understood, only worked around.

---

# Sprint 003 ticket 001 session: on-device `main.py`, button A → heart
# → square tour

Sprint 003, ticket 001
(`clasi/sprints/003-button-a-square-tour-trigger-on-zetuv/tickets/
001-on-device-main-py-button-a-heart-square-tour.md`). Same date, same
physical device (`/dev/cu.usbmodem2121202`, UID
`9906360200052820312bde85515a72e6000000006e052820`). `mbdeploy list`
re-confirmed at the start of this session and again immediately before
every deploy step: `getez`/`zavaz` both still `RADIOBRIDGE` relays
(plus a fourth, unrelated device `vevov` now visible on the bus —
never touched, never a deploy target, `--force-relay` never passed).

## 17. Resident-image probe — `boot`/`config` found stale, `demo_square`
## absence is expected (not stale), decision: NO REFLASH

Per this ticket's own "probe first" discipline, checked the resident
image directly before considering any rebuild:

```
$ mpremote ... exec "import boot; print(sorted(dir(boot)))"
['__class__', '__name__', '_time', 'comms', 'diffdrive', 'microbit']
$ mpremote ... exec "import config; print(sorted(dir(config)))"
['__class__', '__name__']
$ mpremote ... exec "import config; config.load_robot_config"
AttributeError: 'module' object has no attribute 'load_robot_config'
$ mpremote ... exec "import boot; boot.VERSION"
AttributeError: 'module' object has no attribute 'VERSION'
```

**Finding**: the resident frozen `boot`/`config` Python modules are
STALE STUBS relative to this repo's current `src/boot.py`/
`src/config.py` — `config` in particular has essentially no content
beyond `__name__`/`__class__`; `config.load_robot_config` (a function
that exists in the current source) is simply not present on this
image. Cross-checked that `dir()` itself is not the problem (i.e. this
is real staleness, not a `dir()`-on-frozen-module quirk of this port):
`dir(diffdrive)` (the native module, unrelated to this staleness)
returned its full real surface (`begin`, `configure`, `drive`,
`driveDuty`, `estop`, `lastError`, `neutral`, `output`, `start`) with
no problem, and `microbit.display`/`microbit.button_a` are both
present — so `dir()` faithfully reflects real module content on this
build; `boot`/`config` really are old.

**Separately**, `demo_square` does **not** appear in `help('modules')`
— this is **expected, not evidence of staleness**: `demo_square.py` is
deliberately never frozen (sprint 002 ticket 002's own bench log, §16:
"a bench demo script that drives motors as a side effect of being
imported... freezing it would make a bare `import demo_square` from
any REPL an accidental motor-drive trigger"). This ticket's own dispatch
text suggested checking "presence of frozen demo_square" as a
staleness signal — that assumption was wrong (demo_square was never
meant to be frozen); the real, grounded staleness signal turned out to
be `boot`/`config`'s own missing attributes, found independently.

**Decision: no rebuild/reflash this ticket.** This file's (`main.py`'s)
actual requirements — `microbit` (stock, present), `demo_square` (a
filesystem-deployed script, not frozen either way), and a fail-closed
check — do **not** need a current `config`/`boot`. `demo_square` itself
already bypasses both (drives `diffdrive` directly with hardcoded
geometry, per its own module docstring), and `main.py`'s fail-closed
probe (§19 below) was designed specifically to avoid depending on the
stale `config` module. A `--clean` rebuild would fix `boot`/`config`'s
staleness but was judged unnecessary for this ticket's own acceptance
criteria, and not worth the real reflash risk this exact bench has
already hit twice (locked-device mass-erase recovery, §3; the
unexplained `TLM:0:0:0` spew, §12) — **flagged here, disclosed, for
whoever next touches `boot.py`/`config.py`** on zetuv: the resident
image needs a rebuild before `boot.run()`'s six-step sequence (comms/
radio/WiFi/dispatch wiring) can be trusted as current on this unit.

## 18. `/robot.json` — present and valid; `mpremote fs ls` size column
## is unreliable on this port (new finding)

`mpremote ... fs ls :` reported `0 robot.json` (and, later, `0` for
every other file including a fresh `main.py`/`demo_square.py`) —
**this is a display bug/limitation in `mpremote fs ls` on this port,
not real**: direct on-device `os.stat('robot.json')[6]` (and
`open('robot.json').read()`) both independently confirmed the file's
real size, 2413 bytes — the exact same stripped copy sprint 002 ticket
001 produced (`data/zetuv.json`, `_`-prefixed keys stripped, compact
JSON), never wiped since. **No re-copy was needed** — flagged as a
disclosed acceptance-criterion nuance: "presence confirmed" turned out
to mean confirming `mpremote fs ls`'s size column cannot be trusted,
not that the file was actually missing. Do not trust `fs ls`'s size
column on this device/mpremote combination in future sessions; use
on-device `os.stat`/`open` instead.

**Separate, real finding**: `os.stat('/robot.json')` and
`open('/robot.json')` (leading slash) both raise `OSError: ENOENT` on
this port, while the bare form `os.stat('robot.json')`/
`open('robot.json')` (no leading slash) both succeed against the exact
same file. `src/boot.py`'s own `CONFIG_PATH` constant is
`"/robot.json"` (leading slash) — meaning `config.load_robot_config
(boot.CONFIG_PATH)` would ENOENT on this port even with a perfectly
valid `robot.json` present and even on a current, non-stale `config`
module. **Disclosed, not fixed** — `boot.py` is out of this ticket's
file scope; flagged for whoever next touches it. `main.py` (this
ticket) uses the bare, bench-confirmed-working form throughout.

## 19. Filesystem-space and on-device compile-memory limits — two
## distinct constraints, both hit and resolved this session

**Constraint A (flash filesystem capacity)**: the raw filesystem
region is 24576 bytes (sprint 002's own build layout table, unchanged
— no rebuild this session). A fully-documented `main.py` (this
ticket's first draft, matching this repo's own exhaustive-docstring
convention throughout) was 9901 bytes; combined with `robot.json`
(2413) and `demo_square.py`'s raw source (12947), the total (25261)
exceeded the raw region outright — `mpremote fs cp` failed with "No
space left on device" copying `main.py`.

**Constraint B (on-device compile memory, a distinct problem, found
after working around A)**: after precompiling `demo_square.py` to
`.mpy` via `mpy-cross` (12947 → 2346 bytes) specifically to free flash
space, `import demo_square` on-device failed: `ImportError: no module
named 'demo_square'`, despite the file being present. Root-caused by
reading `micropython-microbit-v2/src/codal_port/mpconfigport.h` and
`lib/micropython/py/mpconfig.h` directly: `MICROPY_PERSISTENT_CODE_LOAD`
is not defined in this port's config (defaults to `0`) — **this
firmware build cannot load a `.mpy` file from the filesystem at
runtime at all**; only FROZEN `.mpy` (baked in at build time,
`MICROPY_MODULE_FROZEN_MPY=1`, already true for `boot`/`config`/etc.)
or runtime-compiled `.py` source are supported filesystem-import
paths. This is a genuine, grounded firmware-capability finding, not a
mpy-cross version mismatch guess — confirmed by reading the actual
config macros, not by trial and error alone.

So `demo_square.py` had to go back to raw `.py` source on the
filesystem — which hit a **third**, independent problem: `exec()`-ing
(and equally, plain `import`-ing) the raw 12947-byte source blew the
device's heap during on-device compilation:
`MemoryError: memory allocation failed, allocating 6129 bytes`. This
is a real constraint, not a fluke of a messy verification harness (a
leaner, `gc.collect()`-instrumented harness was tried first and still
failed identically at the same 6129-byte allocation).

**Root-cause fix applied, mirroring sprint 002 ticket 001's own
`data/zetuv.json`-stripping precedent exactly**: `src/demo_square.py`
and `src/main_zetuv_demo.py` (this ticket's own file) both stay FULLY
DOCUMENTED in the repo — neither was edited to shrink it. Only the
**on-device deployment copies** are stripped (module docstring
removed, deploy-time transform only, generated fresh each deploy, not
committed):

```
$ python3 -c "
src = open('src/demo_square.py').read()
text = src.lstrip()
end = text.find('\"\"\"', 3)   # after the opening triple-quote
stripped = text[end+3:]        # drop the whole module docstring
..."
# demo_square.py: 12947 -> 6997 bytes (with a short pointer comment
# added back in, crediting src/demo_square.py + this bench log as the
# full source)
# src/main_zetuv_demo.py: 9901 -> 2999 bytes, same treatment
```

**Verified this resolves constraint C directly**: `gc.mem_free()`
immediately before the tour import showed ~29 KB free (device total
heap is small; this was comfortably enough for the 6997-byte stripped
source), and the tour ran end-to-end without error (§20 below).

**Final on-device footprint**: `robot.json` (2413) + `main.py` (2999)
+ `demo_square.py` (6997) = 12409 bytes — well within the 24576-byte
region, with real headroom remaining (unlike sprint 002 ticket 001's
own JSON-stripping episode, which left almost no margin).

## 20. `main.py` design decisions, bench-grounded

- **`demo_square` invocation, repeatable**: `demo_square.py` is a
  SCRIPT with an unconditional top-level `if _ON_DEVICE: run()` (no
  reload-safe entry point). A plain one-time `import demo_square`
  auto-runs the tour once on the first press but silently no-ops on
  every later press (Python's own import cache) — **independently
  verified this session** with a throwaway `probe_reload.py` module
  (not committed): a bare second `import probe_reload` printed
  nothing, while `sys.modules.pop("probe_reload", None)` before each
  import made the module's top-level `print()` fire on a 3rd *and* a
  4th "press" in the same session. `main.py`'s `run_tour()` uses
  exactly that `sys.modules.pop(...) + import demo_square` pattern —
  bench-verified to make every press independent, satisfying this
  ticket's "repeatable presses" requirement, without needing to run
  the full physical tour more than once to prove the mechanism.
- **Fail-closed check does not use `config.load_robot_config()`** —
  see §17: that module is a stale stub on this image. `main.py`'s own
  `robot_ready()` instead checks `/robot.json` (bare path) is present
  and non-empty via `os.stat`, and that `diffdrive` is importable —
  the two conditions this ticket's acceptance criteria name directly
  ("no /robot.json / diffdrive refuses"), with no dependency on
  `config`'s currency.
- **`__name__ == "__main__"` gating, bench-confirmed not assumed**:
  `codal_port/main.c`'s `microbit_pyexec_file()` compiles and calls the
  filesystem `main.py` as a bare function (`mp_call_function_0`), not
  through the normal import path, so whether `__name__` reads
  `"__main__"` there was not safe to assume by analogy with CPython. A
  throwaway diagnostic `main.py` (written to `/name_probe.txt` on
  boot, then read back after a reset) confirmed directly:
  `__name__ == "__main__"` in exactly this execution context. `run()`
  is gated on that check, which is what lets REPL-driven verification
  (§21) load this file's definitions via `exec(source, ns)` with a
  different `ns["__name__"]` without ever entering the infinite idle
  loop.
- **Main-context discipline**: the idle loop only ever polls
  `button_a.was_pressed()` and sleeps (`IDLE_POLL_MS = 150`) — no
  `microbit.run_every()`/callback registered anywhere in this file.
  `KeyboardInterrupt` is re-raised, never swallowed, in both the tour
  guard and the outer loop's own guard.
- **Idle indicator**: a single-pixel "breathing" brightness pulse at
  the display centre (not a static image) — chosen so the user can
  tell the loop is alive, not merely showing a frozen picture.

## 21. End-to-end REPL-driven verification of `on_button_a()` — the
## exact handler `main.py` wires to button A

Deployed `main.py` (stripped, 2999 bytes) and `demo_square.py`
(stripped, 6997 bytes) to the device filesystem. One `mpremote run
verify_button_a.py` session (a throwaway script, not committed):
loads `main.py`'s definitions via `exec(source, {"__name__": "verify"})`
(so `run()`'s infinite loop is never entered), confirms
`robot_ready() -> True`, then calls `on_button_a()` — the *exact*
function `main.py` wires to button A — directly:

```
VERIFY: mem_free before loading main: 32448
VERIFY: mem_free after loading main: 29408
VERIFY: robot_ready() -> True
VERIFY: mem_free before on_button_a(): 29360
VERIFY: calling on_button_a() directly (the exact handler main.py
VERIFY: wires to button A) -- HEART -> demo_square tour -> idle
demo_square: configure ok
demo_square: begin ok
demo_square: start ok
demo_square: tour has 8 segments
demo_square: segment 0 leg   status ok target_ticks 709.35   delta_left 611.0 delta_right 888.0 mean_delta 749.5 reached True elapsed_ms 1050
demo_square: segment 1 pivot status ok target_ticks 142.6233 delta_left -75.0 delta_right 266.0 mean_delta 170.5 reached True elapsed_ms 350
demo_square: segment 2 leg   status ok target_ticks 709.35   delta_left 622.0 delta_right 808.0 mean_delta 715.0 reached True elapsed_ms 950
demo_square: segment 3 pivot status ok target_ticks 142.6233 delta_left -86.0 delta_right 200.0 mean_delta 143.0 reached True elapsed_ms 300
demo_square: segment 4 leg   status ok target_ticks 709.35   delta_left 728.0 delta_right 778.0 mean_delta 753.0 reached True elapsed_ms 1000
demo_square: segment 5 pivot status ok target_ticks 142.6233 delta_left -92.0 delta_right 197.0 mean_delta 144.5 reached True elapsed_ms 300
demo_square: segment 6 leg   status ok target_ticks 709.35   delta_left 703.0 delta_right 811.0 mean_delta 757.0 reached True elapsed_ms 950
demo_square: segment 7 pivot status ok target_ticks 142.6233 delta_left -91.0 delta_right 219.0 mean_delta 155.0 reached True elapsed_ms 300
demo_square: tour complete
VERIFY: on_button_a() returned
VERIFY: stop-verify position before (2427.0, 4752.0) after 2s (2427.0, 4752.0)
VERIFY: done
```

All 8 segments `reached True`, magnitudes comparable to sprint 002
ticket 002's own bench runs (§15). **Stop-verify**: position held
exactly steady (Δleft = 0, Δright = 0) over 2 s after `on_button_a()`
returned — no drift, matching this ticket's own "encoder delta 0 over
2 s" instruction. `demo_square.neutral()` (its own last hardware call)
plus `main.py`'s `display.clear()` both ran cleanly — the sequence
"HEART shown → tour runs to completion → display cleared" is directly
evidenced end-to-end.

**Idle-prompt visual state**: NOT independently confirmed visually —
no camera/vision access was available to this agent this session
either, consistent with every prior bench session in this file. Left
for the stakeholder to observe directly on the physical press.

## 22. Reset/auto-run verification and final handoff state

```
$ mpremote ... reset
$ sleep 5
$ mpremote ... exec "print('post-reset REPL alive')"
post-reset REPL alive
```

REPL access remained responsive after a real hardware reset + 5 s
settle — confirms `main.py`'s idle loop (poll + `sleep()`) correctly
yields and does not lock up raw-REPL access, consistent with the
`__name__ == "__main__"`-gated auto-run at boot (§20) actually firing.
A **second, final** `reset` + 5 s settle was performed immediately
before handoff, with **no further `exec`/`run` commands issued
afterward** (each of those was independently observed this session to
itself interrupt/re-trigger the boot sequence — matching sprint 002
ticket 001's own §7 process note) — so the device is left genuinely in
its armed idle loop, not mid-verification-session, for the
stakeholder's physical press. `mbdeploy list` immediately after
confirmed `zetuv` still connected and responsive at the same port/UID.

**Process note, new this session**: intermittent `TransportError:
could not enter raw repl` / `OSError: [Errno 6] Device not configured`
failures occurred several times while deploying/verifying, always
recovering on a plain retry within a few seconds (no reset, no
recovery procedure needed beyond re-running the same command). This
matches the same class of transient flakiness already documented in
this file's own §12 (sprint 002 ticket 002) — not treated as a new,
escalation-worthy hardware fault, consistent with that precedent.

## 23. Offline gate

```
$ python3 -m pytest tests/ -q
204 passed, 518 subtests passed
```

204 baseline, unchanged pass count. Adding `src/main_zetuv_demo.py`
initially broke `tests/test_manifest_freeze.py::
test_manifest_lists_exactly_the_src_py_modules` (every `src/*.py` file
must appear in `manifest.py`'s freeze list, by design) — fixed by
extending that test's own `_BENCH_ONLY_MODULES` exclusion set (already
established by sprint 002 ticket 002 for `demo_square.py`) to also
include `main_zetuv_demo.py`, with the reasoning recorded directly in
that test file's own module docstring: a module literally named `main`
must never be frozen (`src/boot.py`'s own docstring — a frozen `main`
would never be found by `mp_main()`'s filesystem-only probe), so this
exclusion is structural, not a workaround.

`python3 -m py_compile src/main_zetuv_demo.py` and `mpy-cross
src/main_zetuv_demo.py -o ...` both clean. `git diff --exit-code --
vendor/` clean. `manifest.py` (repo root) untouched — confirmed via
`git diff --exit-code -- manifest.py`.

## Summary for future readers

1. **`boot`/`config` frozen Python modules on zetuv are stale stubs**
   relative to current `src/boot.py`/`src/config.py` (missing
   `load_robot_config`, `VERSION`, etc. entirely) — disclosed, not
   fixed this ticket (out of file scope; `main.py`/`demo_square` don't
   need them). A future ticket touching `boot.py`/`config.py` on
   zetuv should rebuild first.
2. **`mpremote fs ls`'s size column is unreliable** on this device/
   mpremote combination (always reports 0) — use on-device `os.stat`/
   `open` instead.
3. **Leading-slash filesystem paths ENOENT on this port** — bare
   relative paths (`"robot.json"`, not `"/robot.json"`) are what
   actually works. `src/boot.py`'s own `CONFIG_PATH = "/robot.json"`
   is therefore unreachable as written — disclosed, out of scope here.
4. **This firmware cannot load `.mpy` files from the filesystem at
   runtime** (`MICROPY_PERSISTENT_CODE_LOAD` is off) — only frozen
   `.mpy` or runtime-compiled `.py` source are valid filesystem-import
   paths. Don't try precompiling a filesystem-deployed module again on
   this build without freezing it.
5. **On-device compilation of large (~13 KB) raw `.py` source can
   exhaust this device's heap.** Root-caused and fixed by stripping
   the module docstring from the *deployed* copy only (device-flash-
   time transform, not a repo change) — mirrors sprint 002 ticket
   001's own `data/zetuv.json`-stripping precedent exactly. Any future
   ticket deploying a large filesystem module to zetuv should expect
   to need the same treatment.
6. `main.py` (button A → HEART → `demo_square` tour → idle, repeatable,
   fail-closed on missing/empty `robot.json` or unavailable
   `diffdrive`) is deployed and bench-verified end-to-end via direct
   REPL invocation of `on_button_a()` — 8/8 tour segments reached,
   clean stop-verify, main-context discipline preserved throughout.
   The physical button press itself was left to the stakeholder, per
   this ticket's own instruction.

---

# Sprint 004 ticket 001 session: travel-units root-cause fix + bench
# re-verify attempt (hardware-blocked)

Sprint 004, ticket 001
(`clasi/sprints/004-square-tour-travel-units-fix/tickets/
001-fix-square-tour-travel-units-bench-re-verify.md`), issue
`clasi/sprints/004-square-tour-travel-units-fix/issues/
square-tour-legs-4-5x-short-units-bug.md`. Same date, same physical
device (`/dev/cu.usbmodem2121202`, UID
`9906360200052820312bde85515a72e6000000006e052820`). `mbdeploy list`
re-confirmed at the start of this session and again before every
deploy step: `getez`/`zavaz` both still `RADIOBRIDGE` relays,
`vevov` (a fourth, unrelated device now visible on the bus) never
touched, never a deploy target, `--force-relay` never passed.

## 24. Root cause — units bug in `TICKS_PER_MM`'s two input constants

Stakeholder-observed live (2026-08-19): each "500 mm" leg of the
button-A square tour turns the wheels only ~270° (0.75 rev) — a Nezha
wheel (~145 mm circumference) needs ~3.3-3.6 rev for 500 mm, so legs
ran ~4-5x short. Golden measurement: 270° observed for the OLD leg
target; §15 above's own run-1 leg encoder deltas (725.5/719.0/730.5/
750.5 counts mean-of-both-wheels) for that same 0.75 rev give an
empirical counts-per-revolution of 731.4/0.75 = 975.2 — inside the
issue's own stated 870-1080 range.

**Audit** (per the ticket's own "confirm by reading, don't assume"
instruction): `src/demo_square.py`'s `TICKS_PER_MM = 1.4187` mirrored
`data/zetuv.json`'s `wheels` block (`wheel_diameter_mm=80.77`,
`ticks_per_rev=360` -> `ticks_per_mm = 360/(pi*80.77) = 1.4187`).
Checked `data/tovez.json`'s own `wheels` block: **identical** unqualified
80.77/360/1.4187 trio, with no camera/bench provenance note at all —
unlike every other calibrated group in that file (`motors`, `drive`,
`geometry`, `otos` all carry rich bench-measurement history).
Confirmed via `vendor/nezha_motor.cpp` (line ~129, `NezhaMotor::tick()`)
that `diffdrive.output()`'s `positionLeft`/`positionRight` are
counts-native raw shaft-encoder ticks ("the 0x46 register's own unit
(tenths of a shaft degree) -- sign-corrected only, no unit
conversion"), cross-checked against two independent
`vendor/nezha_motor.h` comments (`kReconfigureRestVelocity`/
`kStopConfirmVelocity`: "5.0 mm/s ... at tovez's 0.7837 mm/deg that is
~6.4 deg/s ~= 64 counts/s" and "8.0 mm/s ~= 102 counts/s" — both derive
to exactly 10 counts/degree). So the counts-vs-mm *convention* was
never the bug (`demo_square.py` already treated `positionLeft/Right`
as raw counts correctly); the arithmetic combining
`wheel_diameter_mm`/`ticks_per_rev` into `ticks_per_mm` was also
correct. **The two INPUT numbers were simply wrong** — unverified
`tovez_nocal.json` template defaults never independently measured on
any real Nezha unit in this repo's `data/` — off by a factor that made
every leg/pivot's encoder-termination target ~4.2-5.3x too small.

## 25. Cross-check against `tovez.json` — conflict found, empirical wins

Per the ticket's explicit instruction, checked whether `tovez.json`
carries a REAL calibrated reference for this quantity. Its `wheels`
block does not (see above — identical unverified template). Its
`motors.travel_calib_left/right` (0.7837) DOES carry a real
vendor-grounded unit — `vendor/nezha_motor.h`'s own comments confirm
these units are mm per DEGREE of raw encoder rotation (at 10
counts/degree) — but that field feeds `fullDutyVelocity`
(`src/config.py`'s `wheel_control_to_diffdrive_config()`,
VELOCITY-mode `drive()`'s plant-gain calibration), which
`src/demo_square.py` never reads: it drives via `driveDuty()` directly,
bypassing `config.py`/`travel_calib` entirely by design (see that
module's own docstring, "Why direct diffdrive calls"). Numerically,
`travel_calib` implies `ticks_per_mm ~= 1/(0.7837/10) ~= 12.76` —
about **1.9x** the empirically-anchored 6.7241 derived below. Per the
issue's explicit instruction ("if they disagree, the empirical bench
number wins"), the empirical anchor governs. `src/config.py`'s own
docstring already flags `travel_calib`'s "x10" multiplier as
underspecified ("No document in this repo elaborates the multiplier's
derivation further than 'x10'"), consistent with it being a
second unverified figure rather than a settled reference.

## 26. Fix applied

`src/demo_square.py`:
```
WHEEL_CIRCUMFERENCE_MM = 145.0     # issue's own stated figure
EMPIRICAL_COUNTS_PER_REV = 975.0   # midpoint of the empirical 870-1080
                                    # range (sprint-002 run-1 derived)
TICKS_PER_MM = EMPIRICAL_COUNTS_PER_REV / WHEEL_CIRCUMFERENCE_MM  # ~6.7241
TRACKWIDTH_MM = 128.0               # UNCHANGED -- caliper-measured,
                                     # not part of this bug
```
`data/zetuv.json`'s `wheels` block updated to match
(`wheel_diameter_mm=46.1521`, `ticks_per_rev=975.0`,
`ticks_per_mm=6.7241`), with a full `_wheels_note` provenance note.
`motors.travel_calib_left/right` deliberately NOT added to
`zetuv.json` — see Sec 25 above; adding it would silently enable
`config.load_robot_config()`'s VELOCITY-mode boot auto-configure path
with an untested figure, reversing sprint 002/003's explicit "zetuv
stays no-cal profile" decision, out of this ticket's scope.
`tests/test_demo_square.py`'s two constant-dependent tests
(`test_leg_ticks_matches_distance_times_ticks_per_mm`,
`test_pivot_ticks_matches_arc_length_times_ticks_per_mm`) updated to
reference the live `demo_square.TICKS_PER_MM` constant rather than the
old hardcoded `1.4187` literal, so a future correction cannot leave a
stale value silently re-asserted.

## 27. Deploy — docstring-stripped copies, same convention as before

Probed the resident filesystem first (per this project's own
probe-before-reflash discipline): `demo_square.py` (6997 bytes, raw
stripped source — confirms sprint 003's own real, bench-verified
outcome; `main.py`'s own docstring claim of a precompiled `.mpy`
deploy is stale/aspirational and does not match what is actually on
the device, consistent with `MICROPY_PERSISTENT_CODE_LOAD` being off
per sprint 003's own Constraint B finding), `robot.json` (2413 bytes),
`main.py` (2999 bytes) all present. `main_zetuv_demo.py`'s
`run_tour()` does `sys.modules.pop("demo_square", None); import
demo_square` — whatever `demo_square.py`/`.mpy` is on the filesystem
at press time is what runs, so only that file needs updating for the
fix to take effect (this module reads nothing from `robot.json` at
runtime — its geometry constants are hardcoded, per its own
docstring — so `data/zetuv.json`'s edit is a repo-source-of-truth
consistency fix, not something that needed pushing to re-verify the
fix itself).

Generated a fresh docstring-stripped `demo_square.py` (same transform
as sprint 002/003: strip the module docstring, add a short pointer
comment) — 18031 bytes raw source -> 7876 bytes stripped (grew ~880
bytes vs. the prior 6997-byte stripped copy, from this ticket's own
added inline comments on the new geometry constants, which sit outside
the docstring and survive the strip). Also regenerated the stripped
`robot.json` from the corrected `data/zetuv.json` (same `_`-prefix-key
strip, compact JSON) — 2417 bytes (barely changed from 2413). Combined
on-device footprint ~13292 bytes, comfortably inside the 24576-byte
filesystem region (sprint 002/003's own established budget).

```
$ mpremote connect /dev/cu.usbmodem2121202 fs cp <stripped demo_square.py> :demo_square.py
$ mpremote connect /dev/cu.usbmodem2121202 fs cp <stripped robot.json> :robot.json
```
Verified sizes on-device via `os.stat` (per sprint 003's own finding
that `mpremote fs ls`'s size column is unreliable on this
device/mpremote combination): `demo_square.py` 7876 bytes, `robot.json`
2417 bytes — both match exactly. `gc.mem_free()` before the tour import:
24928 bytes (comfortably above the ~7876-byte source, matching sprint
003's own precedent of ~29 KB free being sufficient for a
similarly-sized file).

## 28. Software correctness confirmed — target ticks match the fix exactly

REPL-triggered verification (`exec(main.py source, {"__name__":
"verify"})`, `robot_ready() -> True`, then `on_button_a()` called
directly — the exact handler `main.py` wires to button A, same
approach as sprint 003's own Sec 21):

```
demo_square: segment 0 leg   status ok target_ticks 3362.069 ...
demo_square: segment 1 pivot status ok target_ticks 675.984  ...
demo_square: segment 2 leg   status ok target_ticks 3362.069 ...
... (all 8 segments; leg targets 3362.069, pivot targets 675.984)
```
Both figures match the hand-derived correction exactly (500.0 x
6.7241 = 3362.05..3362.07 depending on rounding; (pi/2)*64.0*6.7241 =
675.98) — confirms the software fix is logically correct end-to-end,
independent of the hardware issue below. This is a **4.74x** increase
over the old targets (709.35 -> 3362.069 legs; 142.62 -> 675.984
pivots) — inside the ticket's own expected 4-5x band.

## 29. Bench re-run — HARDWARE-BLOCKED, wheels do not move (new finding,
## not root-caused, escalated)

> **RESOLVED (2026-08-19, same ticket, after stakeholder action)**: the
> stakeholder performed a full physical reset of the robot ("the robot
> has plenty of power, but I completely reset it") — this cleared
> whatever was wedged; power was explicitly ruled out. See "Sec 32
> onward" below for the re-probe, the follow-on timing fix this
> uncovered, and the successful full-tour bench verification. This
> entry is left unedited below, per this file's own established
> append-don't-rewrite convention (Sec 15's own correction note).

The same `on_button_a()` call that confirmed correct target ticks
above showed **every segment timing out** (`reached False`,
`elapsed_ms 3000`, `delta_left`/`delta_right` exactly `0.0`) — no wheel
motion at all, on either wheel, for the full 8-segment tour.

**Systematic-debugging discipline applied** (reproduce, discriminate
cheaply, cap attempts): three independent diagnostics, matching
sprint 002 ticket 002's own bench-verified-working protocol exactly
(`configure(left_port=2, right_port=1, fwd_sign_left=1,
fwd_sign_right=1, max_duty=25.0, full_duty_velocity=0.0,
cycle_period_ms=24)`, `begin()`, `start()`, all returning `"ok"`):

1. **Combined** `driveDuty(20.0, 20.0, 500)` — well above the 6%
   breakaway floor this exact wheel pair has reliably moved at in
   every sprint 002/003 session today. `appliedDutyLeft/Right` read
   20.0 during the pulse (duty genuinely commanded/staged),
   `connectedLeft/Right: True` throughout (I2C acking normally on both
   channels), `cycleCount` advancing normally (kernel fiber alive,
   `cyclePeriodMeasured` ~28 ms, matching every prior session's own
   baseline) — but `positionLeft`/`positionRight` stayed at `0.0` for
   the entire pulse and after.
2. **LEFT alone** (`driveDuty(20.0, 0.0, 500)`) then **RIGHT alone**
   (`driveDuty(0.0, 20.0, 500)`), one wheel at a time (this project's
   own "smallest-necessary-probing" discipline) — same result on
   BOTH: `appliedDuty` nonzero, `connected: True`, `position` frozen
   at `0.0` throughout.
3. **Reset + retest**: a full `mpremote ... reset` + 5 s settle,
   followed by an exact repeat of diagnostic 2 — **identical result**,
   ruling out stale in-session kernel/construct state as the cause.

`lastError()` reported `"ok"` throughout every trial; no `estopped`,
`stallHalted`, or `watchdogFault` flag ever latched. `neutral()` was
called after every trial (no duty left commanded).

**Not root-caused, not fixed** — this symptom set (duty genuinely
applied, I2C still acking on both channels, encoder position frozen at
exactly zero on both wheels regardless of which is driven or in what
combination, reproducing identically across a fresh hardware reset)
does not match this session's own software change (the fix touches
only `TICKS_PER_MM`'s value, never `configure()`/`driveDuty()`'s
parameters, ports, or signs — independently confirmed byte-identical
to prior working sessions by reading the deployed file back). It also
does not match the sprint 002 "combined-drive anomaly" (that was
LEFT-specific and duty-threshold-marginal, root-caused to a units bug
already fixed; this is BOTH wheels, at 20% duty — well clear of any
prior marginal threshold — showing zero response). This reproduces a
NEW condition relative to every prior bench pass today (sprint 002/003
both recorded real, repeated, correctly-signed motion on both wheels
under this exact protocol). Candidates, none confirmed (no camera
access to visually inspect): a mechanical fault (wheel/gearbox
disconnect), a power/battery issue insufficient to actually turn the
motors under load despite the I2C bus and kernel fiber staying healthy,
or an encoder-specific hardware fault on this unit. **Escalated via
`throw_ticket_exception`** rather than pressed further with
higher-duty/longer-duration retries, per this project's own
conservative-duty/minimal-necessary-probing discipline and this
ticket's explicit "if hardware faults, STOP + record + throw exception"
instruction.

## 30. Device left in a safe, armed state

A final `mpremote ... reset` + 5 s settle was performed, with no
further `exec`/`run` issued afterward (matching sprint 003's own Sec
22 handoff convention) — `mbdeploy list` immediately after confirmed
`zetuv` still connected and responsive at the same port/UID. The
corrected `demo_square.py`/`robot.json` remain deployed; `main.py`'s
idle loop (`robot_ready()` only checks `robot.json` presence +
`diffdrive` importability, not actual physical motion) will report
armed/ready and show the breathing idle pulse — but a physical A-press
right now will very likely reproduce the same zero-motion symptom Sec
29 found, since that is a hardware-level issue this ticket's
software-only fix cannot address. Flagged honestly rather than handed
back silently.

## 31. Offline gate

```
$ python3 -m pytest tests/ -q
204 passed, 518 subtests passed
```
204 baseline, unchanged pass count (two existing tests updated to
reference the live `TICKS_PER_MM` constant rather than a hardcoded
stale literal; no new tests added — the corrected constants are
already exercised by the existing parametric/shape tests via that
constant). `python3 -m py_compile src/demo_square.py` and `mpy-cross
src/demo_square.py -o ...` both clean. `git diff --exit-code --
vendor/` clean — vendor/ untouched.

## Summary for future readers

1. **Root cause, software**: `TICKS_PER_MM`'s two input constants
   (`wheel_diameter_mm`, `ticks_per_rev`) were unverified template
   defaults, not a units-convention bug — fixed using the
   stakeholder's own empirical bench anchor (975 counts/rev, ~145 mm
   circumference), per the issue's "empirical wins on conflict"
   instruction, since `tovez.json`'s one real vendor-grounded
   "travel_calib" figure conflicted by ~1.9x AND feeds an unrelated
   kernel field this module never reads.
2. **Software fix independently confirmed correct**: REPL-read-back
   `target_ticks` (3362.069 legs, 675.984 pivots) match the hand
   derivation exactly, a 4.74x increase over the old targets, inside
   the ticket's own expected band.
3. **Bench re-verification is BLOCKED by a new, hardware-level fault**:
   both wheels show zero encoder motion under duty that reliably moved
   them in every sprint 002/003 session today, reproduced across a
   fresh reset, not explained by this ticket's software change. Not
   root-caused this session — escalated via `throw_ticket_exception`.
4. Device left in a safe, connected, armed-but-likely-non-moving idle
   state; corrected files remain deployed for whoever picks up the
   hardware investigation.

---

# Sprint 004 ticket 001 session, continued: exception resolved,
# timing follow-on fix, full corrected tour bench-verified

Stakeholder resolved the Sec 29 exception directly: "the robot has
plenty of power, but I completely reset it, so have at it." Power was
explicitly ruled out; a full physical robot reset plausibly cleared
the wedged Nezha motor board (the Sec 29 signature — duty applied,
I2C connected, encoders frozen — is consistent with a board-level
wedge a physical reset would clear, though this remains the
stakeholder's own diagnosis, not independently root-caused by this
agent). Ticket reopened, resumed same session, same physical device
(`/dev/cu.usbmodem2121202`, UID
`9906360200052820312bde85515a72e6000000006e052820`).

## 32. Re-verify connection + filesystem, cautious motion re-probe

`mbdeploy list`: port unchanged (`/dev/cu.usbmodem2121202`), same UID,
`getez`/`zavaz` still relays, `vevov` still untouched. Filesystem
probed directly (not assumed to have survived the physical reset,
though a micro:bit power/board reset does not touch flash): `robot.json`
(2417 bytes), `main.py` (2999 bytes), `demo_square.py` (7876 bytes,
the pre-timing-fix stripped copy from Sec 27) all present, exact same
sizes as deployed — nothing missing, no re-copy needed at this step.

Cautious single-wheel re-probe FIRST, matching the original
smallest-necessary-probing discipline (modest duty, short lease, one
wheel at a time) before trusting a full tour again:
`driveDuty(10.0, 0.0, 350)` LEFT alone, then `driveDuty(0.0, 10.0,
350)` RIGHT alone. **Motion confirmed alive on both wheels**:
`positionLeft` 0.0 -> 355.0 (post-lease) -> 388.0 (stop-verify, some
coast, matching this drivetrain's own previously-documented coast-down
behavior); `positionRight` then 388.0(unchanged) -> 416.0 -> 452.0 on
the RIGHT-alone pulse. Both wheels respond normally again — the
stakeholder's reset resolved Sec 29's symptom.

## 33. Full tour re-run — a NEW, separate issue surfaces: legs time out
## against the corrected (much longer) target

With motion confirmed alive, reset + 5 s settle, then the same
REPL-triggered `on_button_a()` verification as Sec 28
(`exec(main.py source, {"__name__": "verify"})`, `robot_ready() ->
True`, `on_button_a()` called directly):

All 4 pivots: `reached True`, mean deltas 685.0/678.0/678.5/683.0
against target 675.984, elapsed 900-1000 ms — correct and proportional,
as expected. **All 4 legs: `reached False`**, hitting the
`SEGMENT_TIMEOUT_MS` safety bound at exactly 3000 ms every time, mean
deltas only 2378.5-2493.0 against the corrected target of 3362.069
(~70-74% of target) — below the ticket's own "3000-4000+" expected
neighborhood.

**Root cause of this second issue** (found immediately, not a fresh
mystery): `SEGMENT_LEASE_MS`/`SEGMENT_TIMEOUT_MS` (3000 ms each) were
sized for the OLD, wrong (~4-5x too short) leg targets, which
completed in ~900-1050 ms per every prior session's own bench numbers
(Sec 15, Sec 21) — comfortable 3x margin under the old 3000 ms budget.
Correcting `TICKS_PER_MM` this ticket made every leg ~4.74x longer
without revisiting that budget: extrapolating this run's own
mid-segment rate (slowest observed, 2378.5 ticks / 3000 ms = 0.793
ticks/ms) to the full 3362.069-tick target gives ~4241 ms needed —
past the 3000 ms timeout, and uncomfortably close to the native
binding's own hard 5000 ms single-`driveDuty()`-call lease ceiling
(refused outright above it, never clamped) if simply raised as one
long lease.

**Fix**: `src/demo_square.py`'s `_run_segment()` now REFRESHES the
`driveDuty()` lease periodically (`LEASE_REFRESH_MS = 400`, comfortably
inside a short `SEGMENT_LEASE_MS = 600` safety lease) rather than
holding one lease for the whole segment — this reaches whatever total
drive duration a segment actually needs without approaching the native
5000 ms ceiling, AND keeps the lease's own fail-safe intent tighter
than before (a hung polling loop now loses the wheels within ~600 ms,
not within a multi-second single lease). `SEGMENT_TIMEOUT_MS` raised to
6000 ms (decoupled from the native lease ceiling now that the lease is
refreshed), with real margin over the ~4.2-4.9 s the corrected leg
target needs. A refresh call that itself returns non-`"ok"` stops the
segment immediately (e.g. an estop landing mid-segment), rather than
continuing to poll a segment nothing is advancing. `python3 -m pytest
tests/` re-run clean (204 passed, 518 subtests — no test referenced
the old lease/timeout values), `py_compile`/`mpy-cross` both clean.

Regenerated the stripped deploy copy (same docstring-strip convention):
21063 bytes raw -> 10908 bytes stripped (grew from 7876 due to the new
lease-refresh design's own inline documentation, which sits outside
the docstring and survives the strip). Redeployed to zetuv; `os.stat`
confirmed 10908 bytes on-device, exact match. `gc.mem_free()` before
the tour: 33232 bytes — comfortable headroom (well above the
7876-byte file that already worked fine).

## 34. Full corrected tour — bench-verified, all 8 segments reached

Reset + 5 s settle, then the same REPL-triggered `on_button_a()`
verification once more:

```
demo_square: segment 0 leg   status ok target_ticks 3362.069 delta_left 3186.0 delta_right 3561.0 mean_delta 3373.5 reached True elapsed_ms 4000
demo_square: segment 1 pivot status ok target_ticks 675.984  delta_left -520.0 delta_right 862.0  mean_delta 691.0  reached True elapsed_ms 1050
demo_square: segment 2 leg   status ok target_ticks 3362.069 delta_left 3216.0 delta_right 3555.0 mean_delta 3385.5 reached True elapsed_ms 4000
demo_square: segment 3 pivot status ok target_ticks 675.984  delta_left -633.0 delta_right 786.0  mean_delta 709.5  reached True elapsed_ms 1000
demo_square: segment 4 leg   status ok target_ticks 3362.069 delta_left 3205.0 delta_right 3542.0 mean_delta 3373.5 reached True elapsed_ms 4000
demo_square: segment 5 pivot status ok target_ticks 675.984  delta_left -575.0 delta_right 808.0  mean_delta 691.5  reached True elapsed_ms 950
demo_square: segment 6 leg   status ok target_ticks 3362.069 delta_left 3258.0 delta_right 3522.0 mean_delta 3390.0 reached True elapsed_ms 4000
demo_square: segment 7 pivot status ok target_ticks 675.984  delta_left -558.0 delta_right 830.9999 mean_delta 694.5 reached True elapsed_ms 950
demo_square: tour complete
```

**All 8/8 segments `reached True`.** Legs: mean deltas 3373.5-3390.0
against target 3362.069 (within ~1% of target, all completing at
exactly 4000 ms — comfortably inside the new 6000 ms budget). Pivots:
mean deltas 691.0-709.5 against target 675.984 (within ~5%),
correctly signed throughout (`delta_left` negative, `delta_right`
positive — LEFT/CCW, matching the kernel's own `twist` convention).

**Scale-up vs. the old, wrong run (Sec 15/21)**: old leg mean deltas
were 650-811 (~730 average); new leg means 3373.5-3390.0 (~3380
average) — a **4.63x** increase. Old pivot means were ~142-173
(~155 average, though those numbers were themselves the OLD, wrong
pivot targets' own encoder deltas, not directly comparable
apples-to-apples since the pivot angle math didn't change, only
`TICKS_PER_MM` did); new pivot means ~691-709 (~699 average) — a
**4.5x** increase. Both land inside the ticket's own expected 4-5x
band, and legs land squarely inside the "3000-4000+ counts" numeric
neighborhood the acceptance criteria specify.

**Stop-verify**: position before `(10634.0, 18045.0)`, after 2 s
`(10634.0, 18045.0)` — delta `(0.0, 0.0)`. Clean, no drift, matching
this ticket's own "Δ=0 over 2 s" requirement exactly.

## 35. Device left in a safe, armed state

A final `mpremote ... reset` + 5 s settle was performed, with no
further `exec`/`run` issued afterward (matching sprint 003's own
handoff convention). `mbdeploy list` immediately after confirmed
`zetuv` still connected and responsive at the same port/UID. The
corrected, timing-fixed `demo_square.py` remains deployed; `main.py`'s
idle loop will report armed/ready and show the breathing idle pulse.
Ready for the stakeholder's physical A press.

## 36. Offline gate (final)

```
$ python3 -m pytest tests/ -q
204 passed, 518 subtests passed
```
204 baseline, unchanged pass count. `python3 -m py_compile
src/demo_square.py` and `mpy-cross src/demo_square.py -o ...` both
clean. `git diff --exit-code -- vendor/` clean — vendor/ untouched
throughout this entire ticket.

## Summary for future readers (final)

1. **Root cause, software**: `TICKS_PER_MM`'s two input constants were
   unverified template defaults — fixed using the stakeholder's own
   empirical bench anchor, per the issue's "empirical wins on
   conflict" instruction (Sec 24-26).
2. **Second issue, surfaced only once motion was confirmed alive**:
   the per-segment lease/timeout budget (3000 ms) was sized for the
   OLD, much-shorter leg targets and needed raising for the corrected
   ~4.74x-longer ones — fixed by refreshing `driveDuty()`'s lease
   periodically rather than holding one long lease near the native
   binding's 5000 ms ceiling (Sec 33).
3. **Hardware wedge (Sec 29) resolved by the stakeholder's own physical
   reset**, power explicitly ruled out — re-probed cautiously
   (single wheel, modest duty) before trusting a full tour again
   (Sec 32).
4. **Full corrected tour bench-verified**: all 8 segments reached
   target, legs and pivots both scaled ~4.5-4.7x over the old, wrong
   run, clean stop-verify (Sec 34).
5. Device left connected, reset, armed at the idle prompt, for the
   stakeholder's own physical A press.

---

# Sprint 005 ticket 001 session: wheel diameter corrected to tovez's
# 80.77 mm (stakeholder-confirmed); bench re-verify BLOCKED, zetuv not
# physically connected

Sprint 005, ticket 001
(`clasi/sprints/005-zetuv-wheel-diameter-rescale/tickets/
001-set-zetuv-wheel-diameter-to-80-77-mm-and-rescale-square-tour.md`),
issue `clasi/sprints/005-zetuv-wheel-diameter-rescale/issues/
zetuv-wheel-diameter-from-tovez.md`. Continues directly from sprint
004's own final session above, same date.

## 37. Stakeholder correction, and the "right in revolutions, wrong in
## mm" root cause

Stakeholder, live at the bench (2026-08-19): "Tovez does in fact have
the correct wheel diameter. It's probably correct. You need to set the
wheel size for this Micro:bit to be the same as Tovez's." Sprint 004
(Sec 24-36 above) correctly established `EMPIRICAL_COUNTS_PER_REV =
975.0` (ticks per WHEEL REVOLUTION, from the stakeholder's own
270-degree bench observation) but combined it with an assumed ~145 mm
wheel CIRCUMFERENCE (`wheel_diameter_mm = 46.1521`, backed out of that
145 mm figure) that was itself only the sprint-004 issue's own
*stated* guess, never independently camera/tape-measured. With the
stakeholder now directly confirming zetuv shares tovez's own
`wheel_diameter_mm = 80.77` (circumference = pi * 80.77 = 253.7464
mm), the prior fix's net effect is now clear: sprint 004's legs were
right in REVOLUTIONS (~2 rev was always the correct intent for a
500 mm leg) but wrong in MM, because the wrong circumference converted
that revolution count to the wrong real-world distance — sprint 004's
own `3362.069`-tick leg target is `3362.069 / 975.0 = 3.448` wheel
revolutions, which at the corrected 253.7464 mm circumference is
`3.448 * 253.7464 = 874.9` mm of real travel — 1.75x the 500 mm the
stakeholder actually intended.

## 38. Software fix applied (offline, fully gated)

`data/zetuv.json`'s `wheels` block: `wheel_diameter_mm` 46.1521 ->
80.77 (mirrors `data/tovez.json`'s own value; provenance note:
stakeholder-confirmed 2026-08-19, same wheels as tovez).
`ticks_per_rev` UNCHANGED at 975.0 (sprint 004's own bench-proven
empirical value — not reverted to the disproven `tovez_nocal.json`
template default of 360). `ticks_per_mm` recomputed 6.7241 -> 3.8424
(`975.0 / 253.7464`). Full provenance note updated in place (prior
sprint-004 note text preserved for history inside the new note, per
this file's own append-don't-rewrite convention — see the JSON file
itself). `data/tovez.json` confirmed BYTE-FOR-BYTE UNTOUCHED
(`git diff --exit-code -- data/tovez.json`) — its own
`wheels.ticks_per_rev = 360` inconsistency with this same
empirical-975 finding (same physical kit hardware) is flagged here,
per this ticket's own instruction, as a tovez-bench question for a
separate day, not fixed this ticket.

`src/demo_square.py`: `WHEEL_DIAMETER_MM = 80.77` (new, mirrors
`data/zetuv.json`), `WHEEL_CIRCUMFERENCE_MM` now DERIVED as
`PI * WHEEL_DIAMETER_MM` (~253.7464 mm) rather than a separately-stated
magic number, `EMPIRICAL_COUNTS_PER_REV` UNCHANGED at 975.0,
`TICKS_PER_MM = 975.0 / 253.7464` ~= 3.8424 (was ~6.7241). Recomputed,
software-verified (CPython, no hardware) leg target:
`500.0 * 3.8424` ~= 1921.2 ticks (was 3362.069) — ~1.97 wheel
revolutions, matching the stakeholder's own intended ~2-rev, ~500 mm
leg. Pivot target falls out of the SAME `TICKS_PER_MM` correction
through the unchanged `TRACKWIDTH_MM = 128.0` (caliper-measured, not
part of either this or the sprint 004 bug): `(pi/2) * 64.0 * 3.8424`
~= 386.3 ticks (was 675.984). Full derivation stated in the module
docstring's new "Geometry -- SUPERSEDED sprint 005 ticket 001" section
and in the constants' own inline comments. `SEGMENT_LEASE_MS` /
`LEASE_REFRESH_MS` / `SEGMENT_TIMEOUT_MS` left UNCHANGED, per this
ticket's own scope (the sprint 004 lease-refresh mechanism is out of
scope) — the shorter ~1921-tick leg target only needs LESS time
(~2.4-2.8 s, scaled from sprint 004's own ~4.2-4.9 s bench measurement
by the same ~0.5715x `TICKS_PER_MM` ratio) than the budgets already
comfortably covered, so no timeout adjustment was necessary; comments
updated to state the new expected timing for future readers.

`tests/test_demo_square.py`'s two constant-dependent tests
(`test_leg_ticks_matches_distance_times_ticks_per_mm`,
`test_pivot_ticks_matches_arc_length_times_ticks_per_mm`) already
referenced the live `demo_square.TICKS_PER_MM` constant (sprint 004's
own precedent) rather than a hand-copied literal, confirmed by
reading, not assumed — only their own numeric approx-bounds
(6.7241->3.8424, 676.03->386.28) needed updating to match the new
live value; no test logic changed.

`python3 -m pytest tests/ -q`: **204 passed, 518 subtests passed**
(baseline maintained, no new tests needed — the corrected constants
are already exercised by the existing parametric/shape tests via the
live constant, matching sprint 004's own precedent). `python3 -m
py_compile src/demo_square.py` clean. `mpy-cross src/demo_square.py`
clean (found at
`micropython-microbit-v2/lib/micropython/mpy-cross/mpy-cross` — not on
`$PATH` this session, located directly). `git diff --exit-code --
vendor/` clean — vendor/ untouched throughout.

## 39. Bench re-verify — BLOCKED, zetuv not physically connected to
## this machine

Per this project's own deploy-target discipline, checked the fleet
before any deploy/REPL step:

```
$ mbdeploy list
```
`zetuv` (UID `9906360200052820312bde85515a72e6000000006e052820`) shows
**`CONN: no`, no PORT** — not connected. `getez`/`zavaz` both still
`RADIOBRIDGE` relays (never touched, `--force-relay` never passed).
**New finding**: a physical robot named `tovez` (a DIFFERENT unit, UID
`9906360200052820a8fdb5e413abb276000000006e052820`) is now connected
at `/dev/cu.usbmodem2121202` — the exact port zetuv occupied in every
prior session in this file. `vevov` (UID
`9906360200052820b8e12372c44f4f67000000006e052820`) is also present,
unrelated. Neither `tovez` nor `vevov` was touched at any point this
session — this ticket's own scope, and this project's "zetuv ONLY"
bench-facts instruction, were both respected throughout.

**Not treated as a transient registry/enumeration glitch** — checked
with real evidence, not assumed:
1. `mbdeploy list` re-run twice more, 3 s apart: identical result both
   times (`zetuv` still `CONN: no`, `tovez` still occupying zetuv's old
   port).
2. `mbdeploy probe` (a full live re-scan, not just a registry read):
   identical result — `zetuv` still not connected, `tovez` freshly
   confirmed `NEZHA2` role at that port.
3. Raw OS-level serial enumeration (`ls -la /dev/cu.usbmodem*`):
   exactly 4 ports present (`2121102`, `2121202`, `2121302`,
   `214102`) — matching `getez`/`zavaz`/`tovez`/`vevov` 1:1, with no
   5th port for zetuv to occupy under any name.
4. **Independent cross-check via a completely different USB
   interface** (`pyocd list` — the CMSIS-DAP debug probe, not the CDC
   serial console `mbdeploy`/`mpremote` use): exactly 4 debug probes
   enumerated, UIDs matching `getez`/`tovez`/`vevov`/`zavaz` exactly.
   Zetuv's UID does not appear here either.

Two independent USB interfaces (serial CDC and CMSIS-DAP) both agree:
**zetuv's physical micro:bit is not connected to this machine at all
right now** — not a stale registry, not a `mbdeploy`-level bug, not a
port-naming drift this session's own re-probe could resolve. This is a
genuine hardware/bench precondition failure, not a software fault and
not something this ticket's own code change could have caused (the
device was last seen healthy, connected, and armed at the very end of
sprint 004's own session, per Sec 35-36 above).

**No further recovery attempted** — per this project's own hard rule
for hardware faults (STOP, record, throw an exception rather than
press further or guess at a workaround) and its "never touch
getez/zavaz" / "zetuv ONLY" bench-facts discipline, this agent did NOT
attempt to touch, reset, or deploy to `tovez` or `vevov` in any way
while investigating (both are a different physical robot from this
ticket's own target). The most likely explanation, disclosed as a
hypothesis and not confirmed (no camera/physical bench access
available to this agent): zetuv's USB cable was physically
disconnected or swapped for `tovez`'s between sprint 004's own session
end and this one — a mundane, easily-reversible physical action, not a
device-level fault, but one this agent has no ability to perform
itself.

**Escalated via `throw_ticket_exception`** rather than pressed further.
The stakeholder is at the bench and can very likely resolve this by
simply reconnecting zetuv's own USB cable; once reconnected, the
remaining bench-verification-only acceptance criteria (leg/pivot
deltas, stop-verify, device-armed handoff) can be completed in a
follow-up pass without repeating any of the software work above, which
is already complete, tested, and committed.

## 40. Device state — unchanged (no device touched this session)

No `mpremote`/`pyocd` command was ever issued against `zetuv`,
`tovez`, `vevov`, `getez`, or `zavaz` this session beyond the
read-only enumeration commands above (`mbdeploy list`/`probe`,
`pyocd list`, `ls /dev/cu.usbmodem*`) — no deploy, no reset, no REPL
session, no motor command. Every device's live state (including
zetuv's own last-known-good armed idle state from the end of sprint
004's session, Sec 35-36) is exactly as this session found it.

## Summary for future readers

1. **Software fix, complete and gated**: `data/zetuv.json`'s
   `wheel_diameter_mm` corrected to 80.77 (tovez's own value,
   stakeholder-confirmed same wheel), `ticks_per_rev` preserved at the
   sprint-004 empirical 975.0, `ticks_per_mm` recomputed to 3.8424.
   `src/demo_square.py`'s `TICKS_PER_MM`/leg/pivot targets recomputed
   to match (~1921-tick legs, ~386-tick pivots), with the derivation
   stated in comments. `data/tovez.json` untouched;
   `python3 -m pytest tests/` green at the 204 baseline;
   `py_compile`/`mpy-cross` clean; `vendor/` untouched.
2. **Bench re-verification BLOCKED**: zetuv is not physically connected
   to this machine — confirmed via two independent USB interfaces
   (serial CDC and CMSIS-DAP), re-checked three times, not a transient
   glitch. A different physical robot (`tovez`) now occupies zetuv's
   former port; neither it nor `vevov` was touched.
3. Escalated via `throw_ticket_exception` for the stakeholder (at the
   bench) to reconnect zetuv and clear the block — the software fix
   itself needs no further changes once bench access is restored.

## 41. Re-check after "Zetuv has returned" report — STILL not connected

The stakeholder reported (relayed via the coordinator) that zetuv had
been physically reconnected: "Zetuv has returned." The ticket was
reopened to `in-progress` on that basis. Re-checked immediately, and
again four more times over the following ~15 s, using the same four
independent methods as Sec 39: `mbdeploy list` (x2), a fresh
`mbdeploy probe` re-scan (x2), raw OS-level serial enumeration
(`ls -la /dev/cu.usbmodem*`), and `pyocd list` (the separate CMSIS-DAP
interface). **All five checks agree: zetuv is still not connected.**
Only `getez` (`/dev/cu.usbmodem214102`), `zavaz`
(`/dev/cu.usbmodem2121302`), `tovez`
(`/dev/cu.usbmodem2121202` — still occupying zetuv's former port), and
`vevov` (`/dev/cu.usbmodem2121102`) enumerate, on both the serial-CDC
and CMSIS-DAP interfaces alike. Zetuv's UID
(`9906360200052820312bde85515a72e6000000006e052820`) does not appear
anywhere. One incidental observation, not itself diagnostic: the raw
`/dev/cu.usbmodem*` device-file mtimes advanced between checks (e.g.
`14:17` -> `14:18` across all four existing ports simultaneously),
consistent with *something* happening on the USB bus around that time
(a hub event, a replug of some device), but whatever that event was,
it did not result in zetuv itself enumerating on this machine.

No device command was issued against any board this pass either — only
the same read-only enumeration calls as before. This finding was
reported back to the coordinator directly rather than proceeding on
the unconfirmed premise that bench access had been restored; the
ticket's remaining bench-verification steps (deploy, single-wheel
probe, `on_button_a()` full-tour run, stop-verify, exception
resolution, `done` status) are all still blocked pending an
independently-confirmed live connection.

## 42. Reconnected — bench reshuffled, full corrected tour bench-verified

The coordinator reported having independently verified the
reconnection before re-dispatching: `mbdeploy list` showing zetuv
(correct UID) **CONNECTED on a NEW port, `/dev/cu.usbmodem2121402`** —
the bench had been physically reshuffled, not just zetuv replugged:
`vevov` moved to zetuv's old port (`2121202`), `tovez` moved to
`2121102`. Independently re-confirmed here, before touching anything,
via a fresh `mbdeploy list` and `mbdeploy probe`:

```
ENUM  CONN  DEVICE NAME  COMMON NAME  ROLE          PORT                     UID
--------------------------------------------------------------------------------
1     yes   getez        relay        RADIOBRIDGE   /dev/cu.usbmodem214102   990636020005282017449eac613c0332000000006e052820
2     yes   zetuv        robot        NEZHA2        /dev/cu.usbmodem2121402  9906360200052820312bde85515a72e6000000006e052820
3     yes   zavaz        relay        RADIOBRIDGE   /dev/cu.usbmodem2121302  9906360200052820e9d16c3809a44554000000006e052820
4     yes   tovez        robot        NEZHA2        /dev/cu.usbmodem2121102  9906360200052820a8fdb5e413abb276000000006e052820
5     yes   vevov        robot        NEZHA2        /dev/cu.usbmodem2121202  9906360200052820b8e12372c44f4f67000000006e052820
```

Genuinely connected this time — matches the coordinator's report
exactly. `getez`/`zavaz` unchanged relays, never touched; `tovez`/
`vevov` present but never touched at any point this session (per this
ticket's own "zetuv ONLY" discipline). All subsequent commands
addressed zetuv strictly by its new port, resolved from the UID via
`mbdeploy list` immediately above, never assumed from a prior session.

**Filesystem probe** (probe-before-reflash discipline): `os.listdir()`
showed `demo_square.py`, `main.py`, `robot.json` all present — the
STALE sprint-004 copies (`demo_square.py` 10908 bytes, the old
6.7241/3362-tick constants; `robot.json` 2417 bytes, the old
`wheel_diameter_mm=46.1521`). One `exec` call this step hit the same
intermittent `TransportError: could not enter raw repl` flakiness
documented in sprint 003's own §22 process note — recovered on a plain
retry, no reset needed, exactly as that precedent describes.

**Deploy — fresh stripped copies from the corrected repo sources**:
regenerated via the same transform as every prior session (strip
`_`-prefixed keys from the JSON, compact; strip the module docstring
from `demo_square.py`, add a short pointer comment) —
`robot.json` 2415 bytes (from the corrected `data/zetuv.json`,
`wheels` block now `wheel_diameter_mm=80.77`/`ticks_per_rev=975.0`/
`ticks_per_mm=3.8424`), `demo_square.py` 12495 bytes (from the
corrected `src/demo_square.py` — grew from 10908 due to this ticket's
own added inline derivation comments on the constants block, which sit
outside the docstring and survive the strip). `gc.mem_free()` before
copying: 35184 bytes — comfortable headroom. Copied via
`mpremote ... fs cp`; the `demo_square.py` copy's own follow-up
verification `exec` hit the same intermittent raw-repl flakiness once
more, recovered on retry. On-device `os.stat` confirmed both new sizes
exactly (`robot.json` 2415, `demo_square.py` 12495); `main.py`
unchanged at 2999 bytes (this ticket makes no `main.py` changes).

**Cautious single-wheel probe** (robot had been moved/unplugged/
replugged since its last known-good state — same discipline as every
prior post-reset re-probe in this file): `configure(left_port=2,
right_port=1, fwd_sign_left=1, fwd_sign_right=1, max_duty=25.0,
full_duty_velocity=0.0, cycle_period_ms=24)`, `begin()`, `start()` all
`"ok"`. LEFT alone (`driveDuty(10.0, 0.0, 350)`): `positionLeft`
0.0 -> 288.0 (post-lease) -> 313.0 (stop-verify, some coast, matching
this drivetrain's documented coast-down behavior); `positionRight`
unchanged at 0.0 throughout. RIGHT alone (`driveDuty(0.0, 10.0, 350)`):
`positionRight` 313.0(carried) -> 408.0 -> 438.0; `positionLeft`
unchanged at 313.0. Both wheels respond normally, correctly signed,
real encoder motion — motion confirmed alive before trusting a full
tour.

**REPL-triggered `on_button_a()`** (the exact handler `main.py` wires
to button A, same approach as every prior session's own verification —
`exec(main.py source, {"__name__": "verify"})`, confirm
`robot_ready() -> True`, call `on_button_a()` directly):

```
VERIFY: mem_free before loading main: 32464
VERIFY: mem_free after loading main: 26720
VERIFY: robot_ready() -> True
VERIFY: mem_free before on_button_a(): 26656
VERIFY: calling on_button_a() directly (the exact handler main.py wires to button A)
VERIFY: HEART -> demo_square tour -> idle
demo_square: configure ok
demo_square: begin ok
demo_square: start ok
demo_square: tour has 8 segments
demo_square: segment 0 leg   status ok target_ticks 1921.209 delta_left 1784.0 delta_right 2064.0 mean_delta 1924.0 reached True elapsed_ms 2450
demo_square: segment 1 pivot status ok target_ticks 386.2821 delta_left -300.0 delta_right 539.0  mean_delta 419.5 reached True elapsed_ms 650
demo_square: segment 2 leg   status ok target_ticks 1921.209 delta_left 1761.0 delta_right 2114.0 mean_delta 1937.5 reached True elapsed_ms 2550
demo_square: segment 3 pivot status ok target_ticks 386.2821 delta_left -239.0 delta_right 583.0  mean_delta 411.0 reached True elapsed_ms 700
demo_square: segment 4 leg   status ok target_ticks 1921.209 delta_left 1794.0 delta_right 2103.0 mean_delta 1948.5 reached True elapsed_ms 2450
demo_square: segment 5 pivot status ok target_ticks 386.2821 delta_left -305.0 delta_right 495.0  mean_delta 400.0 reached True elapsed_ms 650
demo_square: segment 6 leg   status ok target_ticks 1921.209 delta_left 1789.0 delta_right 2078.0 mean_delta 1933.5 reached True elapsed_ms 2300
demo_square: segment 7 pivot status ok target_ticks 386.2821 delta_left -295.0 delta_right 533.0  mean_delta 414.0 reached True elapsed_ms 700
demo_square: tour complete
VERIFY: on_button_a() returned
VERIFY: stop-verify position before (6059.0, 11059.0) after 2s (6059.0, 11059.0)
VERIFY: done
```

**All 8/8 segments `reached True`.** Legs: mean deltas
1924.0/1937.5/1948.5/1933.5 against target 1921.209 — within **~1.5%**
of target, matching the ticket's own ≈1922-tick / ≈2-wheel-revolution
/ ≈50 cm expectation almost exactly. Elapsed time per leg (2300-2550
ms) lands squarely inside this ticket's own predicted ~2.4-2.8 s
typical completion window (`src/demo_square.py`'s own updated
`SEGMENT_LEASE_MS` comment), comfortably inside the unchanged 6000 ms
`SEGMENT_TIMEOUT_MS` safety bound. Pivots: mean deltas
419.5/411.0/400.0/414.0 against target 386.2821 — within **~3.6-8.6%**
of target, correctly signed throughout (`delta_left` negative,
`delta_right` positive — LEFT/CCW, matching the kernel's own `twist`
convention), consistent with this drivetrain's own previously
documented right-outpaces-left asymmetry (sprint 002 §15: "RIGHT
consistently outpaces LEFT ... over-rotates on every pivot") — not a
regression, the same known-uncalibrated behavior this demo has shown
every session.

**Stop-verify**: position `(6059.0, 11059.0)` before and after a 2 s
wait — **Δ=(0.0, 0.0)**, no drift, matching this ticket's own "Δ=0
over 2 s" requirement exactly.

**Scale-down vs. sprint 004's own wrong run** (Sec 34 above): sprint
004's leg means were ~3373.5-3390.0 (target 3362.069); this session's
leg means are ~1924.0-1948.5 (target 1921.209) — a **~0.573x**
reduction, matching the ticket's own predicted `3.8424/6.7241 ≈
0.5715x` ratio almost exactly. Sprint 004's pivot means were
~691.0-709.5 (target 675.984); this session's pivot means are
~400.0-419.5 (target 386.2821) — a **~0.58x** reduction, same ratio,
same direction, confirming both legs and pivots scaled consistently
off the single `TICKS_PER_MM` correction as designed.

## 43. Device left in a safe, armed state

A final `mpremote ... reset` + 5 s settle was performed, with no
further `exec`/`run` issued afterward (matching every prior session's
own handoff convention in this file). `mpremote ... exec
"print('post-reset REPL alive')"` confirmed the REPL responsive
post-reset. `mbdeploy list` immediately after confirmed `zetuv` still
connected, responsive, at the same port (`/dev/cu.usbmodem2121402`);
`getez`/`zavaz`/`tovez`/`vevov` all unchanged, none touched at any
point this session beyond the enumeration checks in Sec 39/41. The
corrected, rescaled `demo_square.py`/`robot.json` remain deployed;
`main.py`'s idle loop will report armed/ready and show the breathing
idle pulse. Ready for the stakeholder's physical A press.

## 44. Offline gate (unchanged from commit `c62f4b4`)

No source files changed this session — only the on-device deploy
(a transform of already-committed sources) and this bench log/ticket
documentation. `python3 -m pytest tests/`, `py_compile`, and
`mpy-cross` all still pass exactly as recorded against commit
`c62f4b4` above; not re-run redundantly since nothing in `src/`/
`tests/`/`data/` changed this session.

## Summary for future readers

1. **Bench reshuffle**: between the previous exception and this
   session, the bench's physical USB layout changed — zetuv moved to
   a NEW port (`/dev/cu.usbmodem2121402`), `vevov` took zetuv's old
   port (`2121202`), `tovez` moved to `2121102`. Always resolve the
   target port fresh from `mbdeploy list`/`probe` by UID/name, never
   assume a port from a prior session.
2. **Full corrected tour bench-verified, all 8 segments reached**: legs
   within ~1.5% of the ≈1921-tick target (≈2 wheel revolutions, ≈50 cm,
   as intended), pivots within ~3.6-8.6% of the ≈386-tick target
   (known right-outpaces-left asymmetry, not a regression), clean
   Δ=(0,0) stop-verify.
3. **Scale-down matches the predicted ratio almost exactly**: both legs
   and pivots shrank by ~0.57-0.58x relative to sprint 004's own wrong
   run, matching the `3.8424/6.7241 ≈ 0.5715` ratio the correction
   itself implies.
4. Device left connected, reset, armed at the idle prompt, for the
   stakeholder's own physical A press. No source changes were needed
   this session — commit `c62f4b4`'s software fix stood as-is; only
   the deploy and bench documentation happened here.

---

# Sprint 006 ticket 001 session: 90 mm wheels, button B 50 cm drive,
# config-driven geometry — software complete and gated; bench
# re-verify BLOCKED, zetuv not physically connected

Sprint 006, ticket 001 (`clasi/sprints/
006-zetuv-90mm-wheels-and-button-b-50cm-drive/tickets/
001-90-mm-wheels-button-b-50-cm-drive-config-driven-geometry.md`),
issue `clasi/issues/zetuv-90mm-wheels-button-b-50cm-calibration.md`.
Stakeholder, live at the bench, on branch
`sprint/006-zetuv-90mm-wheels-and-button-b-50cm-drive`: "set up its
wheels to be 90 mm... set the B button to cause it to drive forward
50 cm" — an explicit measure-and-adjust calibration loop.

## 45. Fleet check — zetuv NOT connected, verified BEFORE any deploy
## step (this project's own hard rule)

Per this ticket's own explicit instruction ("verify enumeration BEFORE
deploying anything") and this project's established hardware-fault
discipline (sprint 005 Sec 39/41's own precedent), the fleet was
checked FIRST, before touching any source file's on-device copy:

```
$ mbdeploy list
```
`getez` (`/dev/cu.usbmodem214102`, RADIOBRIDGE relay), `zavaz`
(`/dev/cu.usbmodem2121302`, RADIOBRIDGE relay), `tovez`
(`/dev/cu.usbmodem2121102`, NEZHA2), `vevov` (`/dev/cu.usbmodem2121202`,
NEZHA2) all connected. **`zetuv` (UID
`9906360200052820312bde85515a72e6000000006e052820`) shows `CONN: no`,
no port.**

Not treated as a transient glitch — re-checked with independent
evidence, matching sprint 005's own precedent exactly:
1. `mbdeploy list` re-run 3 s later: identical result.
2. `mbdeploy probe` (a full live re-scan, not a registry read):
   identical result — zetuv still not connected.
3. Raw OS-level serial enumeration (`ls -la /dev/cu.usbmodem*`): exactly
   4 ports, matching getez/zavaz/tovez/vevov 1:1 — no 5th port for
   zetuv.
4. Independent cross-check via a completely different USB interface
   (`pyocd list`, the CMSIS-DAP debug probe, not the CDC serial console
   `mbdeploy`/`mpremote` use): exactly 4 debug probes, UIDs matching
   getez/tovez/vevov/zavaz exactly. Zetuv's UID does not appear.

Two independent USB interfaces (serial CDC and CMSIS-DAP) both agree:
**zetuv's physical micro:bit is not connected to this machine at all
this session.** Not a stale registry, not an `mbdeploy`-level bug, not
resolved by re-probing. `getez`/`zavaz`/`tovez`/`vevov` were never
touched at any point this session beyond these read-only enumeration
commands — no deploy, no reset, no REPL session, no motor command was
ever issued against ANY device this session.

**No further recovery attempted**, per this project's own hard rule for
hardware faults (STOP, record, throw an exception) and its "never touch
getez/zavaz" / "zetuv ONLY" discipline. Per this same project's own
established precedent for this exact "software complete, hardware
blocked" situation (sprint 004 Sec 29-31, sprint 005 Sec 37-40), the
offline-verifiable software work below was completed, tested, and
committed in full — nothing about it depends on bench access, and
completing it now means the remaining bench-verification-only steps are
the ONLY thing blocked once zetuv is reconnected.

## 46. Software work — `data/zetuv.json` wheel diameter

`wheels.wheel_diameter_mm`: 80.77 → 90.0 (stakeholder-directed
calibration starting point, 2026-08-19 — an explicit ITERATION POINT,
not a claimed-final value, per the ticket's own framing). `ticks_per_rev`
UNCHANGED at 975.0 (sprint 004's own bench-proven empirical
counts/wheel-revolution anchor). `ticks_per_mm` recomputed:
`975.0 / (pi * 90.0) ≈ 3.4484` (was 3.8424). Full provenance note
updated in place, prior (sprint 005) text preserved for history inside
the new note, per this file's own established append-don't-rewrite
convention. Calibration formula recorded directly in the JSON's own
note AND here, per the ticket's explicit instruction:

    new_diameter_mm = 90 x (measured_travel_mm / 500)

`python3 -c "import json; json.load(open('data/zetuv.json'))"` confirms
the file stays valid JSON. Per `tests/test_robot_config_data.py`'s own
documented schema-validation note (`data/robot_config.schema.json`
doesn't model the `wheels` group at all — a pre-existing "known gap",
not something this ticket changed), the hand-rolled
`test_robot_files_match_schema_field_constraints` check (the actual
"validates against schema" acceptance criterion this repo enforces, NOT
a whole-document `jsonschema.validate()`) does not even inspect
`wheels` — this change is trivially outside its scope and cannot break
it; confirmed by the full suite passing (Sec 49 below).

## 47. Software work — config-driven geometry: why NOT
## `config.load_robot_config()`, concretely

Read `src/config.py` and `data/zetuv.json` closely before choosing an
approach, per this ticket's own "ground feasibility in what actually
works" instruction. Two independent, concrete, bench-grounded reasons
rule out gating the geometry read behind
`config.load_robot_config()`, either of which alone would already be
disqualifying:

1. Sprint 003's own bench pass (Sec 17 above) found zetuv's resident
   FROZEN `config` module is a STALE STUB on the currently-deployed
   firmware image — `config.load_robot_config` does not exist as an
   attribute at all (`AttributeError`). No rebuild/reflash has happened
   in any session since (sprints 004/005 both explicitly note
   filesystem-copy-only deploys, no `build.sh` step) — this remains the
   resident image's state; not re-probed fresh this session only
   because zetuv was not connected at all (Sec 45).
2. Even on a hypothetically rebuilt, current `config` module,
   `load_robot_config()` would STILL be structurally unusable for
   zetuv's own config: `config.REQUIRED_KEYS` demands
   `motors.travel_calib_left`/`travel_calib_right` and all 15
   `wheel_control` fields as a whole-document fail-closed precondition,
   and zetuv's config deliberately omits `travel_calib_left`/`right`
   (sprint 002's own no-calibration scope decision, unchanged and out
   of this ticket's scope to revisit). Gating the `wheels` group's
   two-field read behind that whole-document gate would make the read
   ALWAYS fail on zetuv's own config specifically — defeating this
   ticket's own stated goal ("each future calibration iteration =
   re-copy robot.json ONLY") before it could ever help.

This ticket's own acceptance criteria explicitly offer an alternative
for exactly this situation ("via `config.load_robot_config()` **or an
equivalent lightweight parse**"). Implemented: `src/demo_square.py`'s
new `geometry_from_robot_config()` — a narrow, fail-SOFT (never raises,
returns `None` on any problem) parse of ONLY
`wheels.wheel_diameter_mm`/`wheels.ticks_per_rev`, with a hardcoded
fallback (90.0 mm / 975.0 counts/rev, mirroring `data/zetuv.json`'s own
updated values) on any failure. Full reasoning recorded in
`src/demo_square.py`'s own module docstring ("Config-driven geometry"
section) for future readers, not just here.

**Where the read happens, and why**: inside `demo_square.py` itself,
re-executed at every fresh `sys.modules.pop("demo_square", None) +
import demo_square` `main.py` already does on EVERY button press
(unchanged mechanism from sprint 003). This means both button A (square
tour) and the new button B (single leg) re-read `/robot.json`'s current
geometry on every press, not just once at boot — a STRONGER guarantee
than a literal one-time "at startup" read, and the one that actually
delivers the ticket's own "re-copy robot.json ONLY" iteration goal: a
stakeholder edits `data/zetuv.json`, regenerates the stripped
`robot.json`, copies it to the device, and the very next press (either
button) picks it up with no redeploy/reset needed.

## 48. Software work — button B handler, single-leg primitive reuse,
## and the auto-run trigger redesign this required

`src/demo_square.py`: added `run_single_leg(distance_mm=LEG_DISTANCE_MM,
ticks_per_mm=TICKS_PER_MM)` — reuses the SAME
`_configure_and_start()`/`_leg_ticks()`/`_run_segment()` pieces `run()`
already uses for every leg (factored `_configure_and_start()` out of
`run()` so both entry points share the identical
configure/begin/start bracketing, byte-for-byte, rather than risking
drift between two copies). No new drive logic — this ticket's own
explicit "reuse, don't reimplement" instruction, satisfied literally.

**A real design problem surfaced implementing this, worked through
methodically, not guessed at**: `demo_square.py`'s existing bottom
trigger (`if _ON_DEVICE: run()`, unconditional) meant ANY import —
fresh or not — ran the FULL square tour as a side effect. Adding a
second, distinct behavior (`run_single_leg()`) that must be selectable
PER PRESS broke this premise: MicroPython's `import` statement takes no
arguments, so there is no way to tell a bare `import demo_square` which
behavior to run. Considered and rejected: stashing a mode flag on a
shared module (e.g. `sys`) before each import — works, but is an
unusual, harder-to-read idiom for a problem with a cleaner fix.
**Chosen fix**: stop relying on import's own side effect entirely.
`main.py`'s `run_tour()`/`run_straight_drive()` now call
`demo_square.run()`/`demo_square.run_single_leg()` EXPLICITLY after
their own `sys.modules.pop(...) + import demo_square` — production
button A/B behavior therefore does not depend on what a bare import
does by itself AT ALL. The bottom of `demo_square.py` keeps a
convenience auto-run for the STANDALONE bench-debug entry point this
project has used throughout (`mpremote ... run src/demo_square.py`),
now gated `if __name__ == "__main__":` rather than `_ON_DEVICE` alone —
this guard is PROVABLY never true for `main.py`'s own import-based
calls (Python's `import` statement guarantees `__name__` is set to the
module's own name, `"demo_square"`, for every import, on any Python
implementation — confirmed directly, not assumed, via
`tests/test_demo_square.py::test_module_does_not_auto_run_on_plain_import`
and by the simple fact that this test file's own top-level `import
demo_square` would already have raised `RuntimeError` at collection
time — no `diffdrive` off-device — if the old unconditional trigger
were still in place; the full suite collecting and passing (Sec 49) is
itself evidence the guard change works as intended for the import
path).

**Disclosed, not bench-verified this session**: whether `mpremote ...
run <file>.py` itself executes with `__name__ == "__main__"` — needed
only for the STANDALONE bench-debug convenience path, NOT for
production button A/B behavior (which never depends on it). Reasoned
from existing bench evidence already in this file (sprint 003's own
Sec 20-21: the REPL verification scripts had to explicitly override
`__name__` to `"verify"` specifically because the REPL's own default
execution namespace already has `__name__ == "__main__"`, and
`mpremote ... run` sends a file's source through that same raw-REPL
execution mechanism) but genuinely not independently confirmed this
session — zetuv was not connected at all (Sec 45). If this reasoning
turns out wrong, the only failure mode is the standalone
`mpremote run src/demo_square.py` convenience silently doing nothing
(non-destructive, trivially diagnosed with a one-line `print(__name__)`
probe, the same technique already used for `main.py`'s own `__name__`
verification) — flagged plainly here and in `src/demo_square.py`'s own
module docstring for whoever next has bench access to confirm directly,
before or as part of the bench-verification steps below.

`src/main_zetuv_demo.py`: added `button_b` import, `Image.ARROW_E` as
the button-B display indicator (distinct from button A's `Image.HEART`,
per the acceptance criteria), `STRAIGHT_DRIVE_DISTANCE_MM = 500.0`,
`run_straight_drive()`, `on_button_b()` (mirrors `on_button_a()`'s
shape exactly — indicator, drive, fault-guarded, clear,
`KeyboardInterrupt` always re-raised), and `run()`'s idle loop now polls
`button_b.was_pressed()` alongside `button_a.was_pressed()`, same
ready/not-ready gating. `run_tour()` updated to call
`demo_square.run()` explicitly (see above); its own docstring and two
other stale-comment sites (`manifest.py`, `tests/test_manifest_freeze.py`)
were updated to stop describing the old "bare import auto-runs the
tour" mechanism as current, since it no longer is.

## 49. Offline gate

```
$ python3 -m pytest tests/ -q
216 passed, 518 subtests passed in 0.21s
```
204 baseline + 12 new tests: 8 covering `geometry_from_robot_config()`'s
happy path and every disclosed failure mode (missing file, malformed
JSON, missing group, missing field, non-numeric, non-positive diameter,
negative ticks_per_rev) per this ticket's own Testing section
suggestion; 1 confirming the off-device fallback constants
(`GEOMETRY_SOURCE == "hardcoded fallback"`, 90.0/975.0); 1 confirming
`run_single_leg()`'s own off-device `RuntimeError` contract (mirrors
`run()`'s own existing test); 1 confirming `run_single_leg()`'s default
distance matches `LEG_DISTANCE_MM` (500.0); 1 confirming the `__name__`
guard's import-path behavior directly. Two existing tests
(`test_leg_ticks_matches_distance_times_ticks_per_mm`,
`test_pivot_ticks_matches_arc_length_times_ticks_per_mm`) updated to the
new live `TICKS_PER_MM`/pivot-tick values (~3.4484/~346.67, was
~3.8424/~386.28), per this ticket's own instruction that stale
constant-dependent tests follow the live value.

```
$ python3 -m py_compile src/demo_square.py src/main_zetuv_demo.py manifest.py tests/test_demo_square.py tests/test_manifest_freeze.py
```
Clean.

```
$ micropython-microbit-v2/lib/micropython/mpy-cross/mpy-cross -o /tmp/demo_square.mpy src/demo_square.py
$ micropython-microbit-v2/lib/micropython/mpy-cross/mpy-cross -o /tmp/main_zetuv_demo.mpy src/main_zetuv_demo.py
```
Both clean (mpy-cross located directly under
`micropython-microbit-v2/lib/micropython/mpy-cross/mpy-cross`, not on
`$PATH` this session, matching sprint 005's own precedent).

```
$ git diff --exit-code -- vendor/
```
Clean — `vendor/` untouched.

## 50. Device state — unchanged (no device touched this session)

No `mpremote`/`pyocd` command was ever issued against `zetuv`, `tovez`,
`vevov`, `getez`, or `zavaz` this session beyond the read-only
enumeration commands in Sec 45 — no deploy, no reset, no REPL session,
no motor command. zetuv's own last-known-good state (armed idle loop,
end of sprint 005's own session, Sec 43) is exactly as this session
found it — still not physically connected to this machine.

## Summary for future readers / whoever picks up the bench-verify

1. **Software complete, tested, and committed**: `data/zetuv.json`'s
   `wheel_diameter_mm` → 90.0 (stakeholder-directed iteration point);
   `src/demo_square.py` gets config-driven geometry
   (`geometry_from_robot_config()`, fail-soft, narrow parse — NOT
   `config.load_robot_config()`, for two concrete, disclosed reasons)
   and a new `run_single_leg()` entry point reusing the existing
   encoder-terminated, lease-refreshed primitive; `src/
   main_zetuv_demo.py` gets a button-B handler
   (`Image.ARROW_E` → 500 mm straight → idle) built on top of it.
   `python3 -m pytest tests/` green (216, up from 204 baseline);
   `py_compile`/`mpy-cross` clean; `vendor/` untouched.
2. **Bench re-verification BLOCKED**: zetuv is not physically connected
   to this machine — confirmed via two independent USB interfaces
   (serial CDC and CMSIS-DAP), re-checked twice, not a transient
   glitch, matching sprint 005's own exact precedent. `getez`/`zavaz`/
   `tovez`/`vevov` present and untouched.
3. **One disclosed, not-yet-bench-verified design assumption**: whether
   `mpremote ... run <file>.py` executes with `__name__ == "__main__"`
   (affects ONLY the standalone bench-debug convenience path for
   `demo_square.py`, not production button A/B behavior, which calls
   its target function explicitly either way) — reasoned from existing
   bench evidence, flagged for direct confirmation once bench access is
   restored.
4. Escalated via `throw_ticket_exception` for the stakeholder (at the
   bench) to reconnect zetuv — the remaining acceptance criteria
   (REPL-invoked bench re-run of both handlers: B's ≈1724-tick delta and
   straightness, A's legs also ≈1724 ticks/pivots ≈347, clean
   stop-verify, device left armed) can be completed in a follow-up pass
   without repeating any of the software work above.

## 51. OOP session (sprint 006 nuked): deploy + bench-verify of the 90 mm / button-B work

Stakeholder ended sprint 006 mid-flight ("this is ridiculous") and opted
out of process (`clasi oop on`, 8 h). The interrupted programmer's
software work (Secs 46–50) was recovered from the working tree intact —
216 tests green — and finished out-of-process by the team-lead directly.

**New on-device finding**: this image ships NEITHER `json` NOR `ujson`
(`help('modules')` on zetuv) — the deployed `demo_square.py`'s
`import ujson`/`json` fallback chain raised `ImportError` at first
on-device import. This also means the frozen `config` module's own
`ujson` import path has never been executable on this image (consistent
with Sec 17's stale-frozen-modules finding). Fix (committed):
`geometry_from_robot_config()` now uses a dependency-free two-key string
scan (`_scan_number()`) of the compact deployed `/robot.json` — no JSON
parser needed; both keys appear exactly once in the deployed config.
All 8 geometry tests pass unchanged (216 total).

**Deploy**: stripped copies of `robot.json` (2414 B), `demo_square.py`
(6858 B), `main.py` (2350 B) → zetuv at `/dev/cu.usbmodem2121402`
(UID-verified; the USB drop Secs 45/50 recorded was transient —
third flake today).

**On-device geometry verification**: `GEOMETRY_SOURCE: robot.json`,
`TICKS_PER_MM: 3.448357`, 500 mm → 1724.179 ticks. Config-driven read
is LIVE: future calibration iterations are a robot.json re-copy only.

**Button-B drive verification** (REPL-invoked `main.on_button_b()` —
the exact production path): target 1724.2 ticks → delta_left 1600.0,
delta_right 1936.0, mean 1768.0 (+2.5%), reached True, 2250 ms, clean
stop (appliedDuty 0/0, velocity 0/0, no watchdog fault). Known
right-outpaces-left asymmetry visible (±10% per wheel around the mean):
the run will veer slightly left — stakeholder should measure distance
along the robot's actual path.

**Device state**: reset, re-armed at the idle breathing prompt.
A = square tour (legs now also 1724 ticks), B = 50 cm straight.

**Calibration loop reminder**: after a button-B run, measure actual
travel X mm; next `wheel_diameter_mm = 90 × (X / 500)`. Edit
`data/zetuv.json`, re-strip + re-copy `/robot.json`, reset. No code
changes needed.

## 52. OOP session continued: tovez becomes the calibration robot

Stakeholder switched the bench target to tovez ("let's move over to
tovez"). zetuv disconnected again (4th USB drop today) — left as-is.

**Tovez flashed** with a fresh `--clean --with-diffdrive --with-wifi`
build (BUILD_EXIT_CODE:0, gate tests 5/5) by UID
`...a8fdb5e413abb276...`; its previous (non-MicroPython) firmware was
erased with stakeholder approval.

**Config-driven WIRING added** (`_wiring_from_robot_config()`): wiring
is per-robot — zetuv measured +1/+1, tovez's calibrated config says
fwd_sign_left=-1 — so `demo_square` now scans motors.left_port/
right_port/fwd_sign_left/fwd_sign_right from `/robot.json` too
(fallback: zetuv's bench-measured values). `data/tovez.json`'s wheels
trio corrected (ticks_per_rev 360 → 975.0 empirical, ticks_per_mm →
3.8424; diameter 80.77 stakeholder-confirmed).

**On-device verification (tovez)**: GEOMETRY robot.json 3.8424;
WIRING robot.json 2/1/-1/+1. Per-wheel probes healthy (left-only +860,
right-only +1264, correct signs).

**New finding — combined-drive breakaway, root-caused by probes**: the
50 mm probe leg stalled the LEFT wheel (delta 0) while right drove —
same signature as sprint-002's zetuv anomaly. Probes: combined 25%
both wheels fine (2073/2489); staggered 20% fine (2133/1805). Cause:
`SEGMENT_DUTY_PERCENT = 6.0` sat below tovez's left wheel's
COMBINED-LOAD breakaway (fine solo, stalls under shared load).
Fix: 6.0 → 15.0 (encoder-terminated segments — distance unaffected,
only speed; still well under the 25% authority rail).

**Full square tour on tovez — PASS**: all 8 segments reached. Legs
1934–1985 mean ticks vs 1921 target (+0.7–3.3%), ~1.45 s each;
pivots 388–432 vs 386, correctly counter-rotating (left negative /
right positive = left pivot with tovez's signs). Right-outpaces-left
asymmetry persists on legs (right ~+30% ticks vs left) — the square
veers; open-loop duty, known behavior.

**Device state**: reset, armed at idle prompt. A = square tour,
B = 50 cm straight. Calibration loop: press B, measure travel X mm,
next wheel_diameter_mm = 80.77 × (X / 500) for tovez.

## 53. Straightness fix — encoder-balancing PI controller (stakeholder rejection of the veering tour)

Stakeholder rejected the §52 tour: "isn't even remotely square... you
can't give me a square turn unless you can drive straight." Correct —
legs ran open-loop duty with ~30% right-lead; distance was
encoder-true but heading drifted.

Fix in `demo_square._run_segment()` (all offline-testable, 7 new unit
tests):
1. `balanced_duties()` — P-trim on |tick-progress| mismatch, re-issued
   every 50 ms poll (also subsumes the lease refresh timer).
2. P-only bench result: legs improved 30% → ~6% standing imbalance
   (≈14°/leg arc) — classic P steady-state offset, not good enough.
3. Added integral bias (BALANCE_KI=0.004, clamp ±8%) carried ACROSS
   segments of the same kind (`_segment_bias`): leg 2+ / pivot 2+
   start pre-compensated.

Bench result (tovez, full tour): legs 1986/1978, 1967/1964, 1942/1952,
1948/1942 — left/right within 0.15–0.5% (straight). Pivots converge as
the bias learns: 28% → 10% → 0.3% → 6% asymmetry. All 8 segments
reached; ~1.4 s/leg.

Also this session: tovez robot power was OFF for a stretch (REPL dead,
debug-probe reset + power-on recovered it); one mangled mid-power-off
file copy (8555 vs 8334 bytes) was caught by size verification and
recopied — verify-by-size is now the deploy discipline.

Device re-armed: A = square tour (now straight-legged), B = 50 cm
calibration drive (same balanced primitive).

## 54. Stakeholder rejection #2 — full teardown and rebuild on the bench (tovez)

Stakeholder rejected the §53 square outright and directed: verify the
encoder-configuration hypothesis first, tear all adjustments down,
rebuild, and bench-verify before reporting.

**Encoder-config hypothesis tested (port-swap experiment)**: single-
wheel drives at 15%/1 s under BOTH port mappings. Config A (left=p2,
right=p1): p2=1036, p1=1663. Config B (swapped): p1=1628, p2=1105. The
~1.5-1.6x asymmetry FOLLOWS THE PHYSICAL PORT/MOTOR, not the software
side → binding/leaf configs (audited: symmetric, only port+sign differ)
are exonerated. The duty-sweep ratio COMPRESSES with duty (1.47@15%,
1.22@20%, 1.20@25%) → additive-friction plant asymmetry (left motor
sticky; matches its proven higher breakaway), NOT encoder scaling
(which would be duty-independent). Encoders consistent; tick-locking IS
valid for straightness. OTOS not fitted/answering on tovez (init False)
— no optical ground truth available.

**Stage-0 baseline (all adjustments off)**: raw 15% combined, 1 s ×3:
left 1089/1095/1150 vs right 1767/1617/1722 (ratio ~1.5, repeatable).

**Actual geometric killers found in own telemetry**: (1) coast
overshoot — corners over-rotated +0.5..19% randomly (pinwheel); (2)
corner 1 always unlearned — main.py's reload-per-press wiped learned
state; (3) 15% pivots last ~300 ms — too fast for 50 ms polls to act.

**Rebuild**: two-phase drive (full duty → 12% creep at 80% leg / 50%
pivot progress); adaptive coast-lead (stop early by learned per-kind
coast, seeds leg=60/pivot=100); PI balance retained (valid per the
port-swap evidence) with bench-informed bias seed (−3.5%); pivots
slowed to 12% duty; polls 25 ms; learned state persisted to
/tour_state.csv across main.py's module reloads.

**Verification (two consecutive full tours, FINAL post-coast deltas)**:
Run 1 — legs +2.9/+1.1/+1.6/+0.8%, corners −3.6/−1.1/−0.7/−1.4%.
Run 2 — legs −0.5/−1.9/+0.9/−0.5%, corners −0.7/+0.3/+7.0/+1.9%.
L/R leg match ≤1.3%. 14/16 segments within ±4%; worst corner +7%
(≈6°, one occurrence).

**Remaining systematic not measurable without external heading truth**:
absolute corner angle scales with TRACKWIDTH_MM (128, provenance
uncertain for tovez). If the square consistently over/under-rotates at
EVERY corner by the same amount, trim trackwidth_mm:
new = 128 × (observed_turn_deg / 90).

Device re-armed (A = tour, B = 50 cm straight, both on the rebuilt
controller). 228 offline tests green.
