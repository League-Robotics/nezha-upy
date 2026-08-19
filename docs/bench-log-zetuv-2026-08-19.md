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
