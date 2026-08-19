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
