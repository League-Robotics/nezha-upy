# Bench acceptance procedures + student-facing API contract (M6)

Sprint 001, ticket 009 (Part A/B as originally written); Part B §B.1
extended by sprint 006, ticket 008, to cover the additive
generator/step-driven mode (ticket 007) alongside the original
background/fiber mode. This document is itself a documentation
deliverable — it does not run any hardware step. It writes down the
procedure the **stakeholder** runs on hardware, per the sprint's
constraint that no hardware step is a ticket acceptance criterion the
programmer performs (see `docs/design/specification.md` §2, "Hardware
acceptance is performed by the stakeholder on master").

Two parts:

- **Part A** — the bench acceptance procedures: the M1→M6 hardware
  ladder, in order, each step naming its exact command and bench
  fixture.
- **Part B** — the student-facing API contract: the wheel-control
  contract, the watchdog visibility contract, lease semantics, and the
  public robot API surface as actually built.

---

## Part A — Bench acceptance procedures

### A.0 What this procedure is *not*

Tickets 001–008 already carry their own **offline** gates — golden
vectors, CPython loopback engine tests, source-review checks on the
native binding, unit tests for config/motion/telemetry — and those are
green (`python3 -m pytest tests/` → 187 passed, as of this ticket).
**None of that offline work is repeated here.** This document is only
the hardware leg: the steps that need a real micro:bit, a real WiFi
module, and a real relay/host tooling session, none of which can run in
CI. The table in §A.1 maps each hardware step below back to the offline
ticket/tests it builds on, so it is visible at a glance which half of a
milestone's gate is already closed and which half this procedure
closes.

### A.1 What tickets 001–008 already verified offline (not re-run here)

| Milestone | Ticket | Offline-verified already | Where |
|---|---|---|---|
| M0 | 001 | `./build.sh --clean` → hex; flash-end < `_fs_start` (0x6D000); `MICROPY_NLR_SETJMP=1`; overlay keys present | `tests/test_build_gate.py` |
| M1 | 004 | `diffdrive`/`robotio` API surface registered (source review, matches `native/moddiffdrive_glue.c`'s method tables); boot zero-write wired before `mp_init`; VM-hook watchdog never yields and covers both the busy-wait and polling-idiom trigger shapes by design (no branch on *how* the stall happened); 5000 ms lease ceiling enforced by rejection; `cycleOverrunCount_` exposed; vendor sync-diff clean | Source review (no CPython test framework applies to the native binding itself), `git diff --exit-code -- vendor/`, `native/README.md` |
| M2 | 003 | Wire codec 8/8 against the golden-vector fixture; encode/decode round-trip | `tests/unit/test_wire_golden_vectors.py`, `tests/fixtures/wire_golden_vectors.txt` |
| M3 | 005 | `comms.py` dispatch order byte-exact vs `dispatchLine()`; banner/READY byte-exact; ack ring depth 12, `corr_id<<4\|err` packing, 3 repeats; telemetry emit policy (AUTO, silent-while-parked, 25 ms, pending-ack-forces-emission); radio fragment reassembly | `tests/test_comms_loopback.py`, `tests/test_radio_shim_fragments.py` |
| M4 | 006 | `wifi_at.py` AT state machine (`CIPMUX=1` sequencing, one-CIPSEND-per-datagram, ≥50 ms TLM throttle, READY-on-new-peer-edge) against a mock serial object | `tests/test_wifi_at.py` |
| M5 | 007 | `config.py` fail-closed required-key validation + `wheel_control`→`DiffDrive::Config` mapping (`travel_calib`×10); `motion.py` queue/stop-condition/timeout-fault/replace logic, explicit ms-not-seconds regression assertion; `telemetry.py` 22-field frame assembly incl. `watchdog_fault`/`cycle_overrun_count`; `manifest.py` freeze-list completeness | `tests/test_config.py`, `tests/test_motion.py`, `tests/test_telemetry.py`, `tests/test_manifest_freeze.py` |

Cross-cutting: `python3 -m pytest tests/` — 187 passed, 417 subtests
passed, as of this ticket's writing. Re-run this before starting the
hardware ladder below; if it is not green, stop and fix the offline
gate first — the hardware ladder assumes it.

### A.2 Bench fixture (fixed; applies to every step below)

Per stakeholder decision 2026-08-19 (`docs/design/specification.md`
§2/§9, sprint issue `test-on-microbit-tovez-radio-channel-3.md`):

- **Bench robot**: micro:bit **tovez** (`data/tovez.json`'s
  `connection.device_announcement_name` = `"tovez"`;
  `connection.serial_last_6` = `f137c0` is the last-6 fragment of
  tovez's device UID already tracked in this repo's config data — get
  the *full* UID `mbdeploy` needs from your local bench device roster,
  radio-robot bench convention).
- **Radio channel**: **3** — already baked into
  `data/tovez.json`'s `connection.radio_channel` field (not something
  you set separately).
- **Build**: `./build.sh --clean --with-diffdrive --with-wifi` (implies
  `--with-yield`) from the repo root. Produces
  `micropython-microbit-v2/src/MICROBIT.hex`. Confirm the script's own
  tail output: `arm-none-eabi-size` report, then `Hex ready.`
- **Deploy**: `mbdeploy deploy --hex
  micropython-microbit-v2/src/MICROBIT.hex <tovez-UID>` — **by UID
  only**, never by copying to a mounted drive letter (radio-robot bench
  convention; a UID-targeted deploy is unambiguous about which micro:bit
  on the bench gets flashed).
- **On-device robot JSON** (ticket 010): copy `data/tovez.json`'s
  content onto the device filesystem as `/robot.json` — this is a
  filesystem-content step, separate from flashing the hex (the built
  image is robot-agnostic; `boot.py` reads whichever robot's JSON is
  present at this one fixed path — see `src/boot.py`'s own module
  docstring). Without it, boot still completes (fail-closed: comms/
  banner/READY still come up, motion is refused) but every step below
  that needs real motion (A.4 onward) will not move.
- **Settle**: wait **~5 s** after `mbdeploy` reports success before
  opening a REPL or expecting a radio/WiFi response.
- **WiFi module**: **power-cycle it** before any step that touches the
  WiFi transport (step A.7 below) — its AT state persists across nRF
  reflashes, so a fresh flash of the micro:bit does **not** reset it.
- **Known defect — TLM flood blocks the `mpremote` REPL handshake**: a
  booted robot streams `TLM:0:0:0` over USB serial at ~19 Hz and does
  **not** stop on `TLM:OFF` (measured on the bench 2026-08-20). This is
  not a cable or hardware fault — the board is demonstrably listening
  the whole time (`PING`/`ID`/`VER` all answer normally) — some emitter
  is running without consulting `Comms.telemetry.mode`. The flood is
  enough to make `mpremote` report the misleading "port in use by
  another program" error instead of connecting, because it never gets
  a quiet moment to complete its handshake. Tracked separately, not
  fixed by this sprint: `clasi/issues/tlm-stream-ignores-tlm-off.md`.
  If a REPL connection (USB, either mode — see Part B §B.1) refuses to
  come up and the port otherwise looks fine, suspect this before
  suspecting the cable or the board.

### A.3 Boot wiring assembles the engine automatically at power-on

Ticket 010 closed the gap this section used to document (the section
below is what replaced it — kept at the same heading number since every
later step in this document cross-references "A.3"). The image now
boots directly into the v5 engine: a frozen `src/boot.py` (grounded
against `micropython-microbit-v2/src/codal_port/main.c`'s actual boot
sequence, not assumed to be a conventional `main.py` — see that
module's own docstring for the full mechanism) runs automatically on
every power-on, before the REPL loop starts:

1. Loads the robot's JSON config, fail-closed.
2. `diffdrive.configure(...)` — only if the config loaded successfully.
   **Correction (sprint 006 ticket 008, reading `src/boot.py`'s own
   step-2 comment):** boot deliberately does **not** call
   `begin()`/`start()` itself — re-configuring under an already-live
   kernel fiber would orphan it, so boot only stages a valid config and
   leaves `begin()`/committing to a mode (Part B §B.1) to the first real
   motion consumer. This section previously said
   `configure/begin/start`; that was inaccurate for as long as
   `boot.py` has existed (ticket 010) — not a recent behavior change.
3. Brings up `comms.Comms` + the radio transport unconditionally; brings
   up the WiFi transport only when `wifi_secrets.json` is present.
   Also wires `motion.RobotDispatch` (`motion.MoveQueue` +
   `config.ConfigDispatch`) as the dispatch, so MOVE/WHEELS/STOP/ESTOP/
   GO_TO/CALIBRATE verbs reach the kernel directly, with no manual
   step — replacing `NullDispatch`, which used to leave every wire
   client's motion commands acked-never/dropped until someone typed the
   composition at the REPL.
4. Starts the scheduled pump, wired to `microbit.run_every()` (the
   port's own periodic-callback mechanism — no native timer change was
   needed; see `boot.py`'s own docstring for why this hook is safe:
   `PumpTimer.tick()` only ever queues work via
   `micropython.schedule()`, matching the landmine ledger's
   never-run-Python-from-an-IRQ-directly rule).
5. Emits banner/boot/READY.

**Practical effect on this ladder**: every step below (A.4 onward) now
just requires power-on-and-verify — **no REPL assembly step, and no
bench-local `main.py`, is needed any more.** The one remaining bench
precondition (not a wiring gap, a data precondition — see A.2's own
bullet) is that the bench robot's JSON content is present on the
device filesystem at `/robot.json` before power-on; `boot.py`'s own
module docstring records why that path is fixed and robot-agnostic
(the built hex itself carries no per-robot data — `build.sh` has no
per-robot flag — so per-robot specialization is entirely a filesystem
concern, decided at bench-flash time). Absent or invalid `/robot.json`
does not brick the bench: boot falls back to its fail-closed path
(comms/banner/READY still come up, radio still registers, motion is
simply refused) — exercised directly by A.5's own safety cases, not a
new hardware step this document adds.

### A.4 Step 1 — REPL wheel spin (smallest-visible-pulse first)

**Preconditions**: A.2's build+deploy+settle done; USB REPL connected
(e.g. `mpremote connect /dev/<port>`, per the pattern already used
during the prior MicroPython exploration).

**Commands** (typed at the REPL):

```python
import diffdrive
diffdrive.configure(left_port=2, right_port=1,
                     fwd_sign_left=-1, fwd_sign_right=1,
                     max_duty=15.0, full_duty_velocity=7.837,
                     cycle_period_ms=24)
diffdrive.begin()
diffdrive.start()
diffdrive.driveDuty(5.0, 5.0, 200)   # smallest visible pulse: low duty, short lease
```

**Units correction (sprint 002 ticket 002,
`docs/bench-log-zetuv-2026-08-19.md`)**: `max_duty` and
`driveDuty()`'s `dutyLeft`/`dutyRight` are PERCENT (0-100), matching
the vendored kernel's own field comments (`vendor/differential_drive.h`:
`Config.maxDuty`/`Command.dutyLeft` `// [%]`) — this section previously
showed `max_duty=0.15`/`driveDuty(0.05, 0.05, ...)`, which reads as
"15%"/"5%" but is actually ~0.15%/~0.05%, a rail far below the write
path's own 3% output-deadband floor. That collapses every commanded
duty to the SAME ~3% floor regardless of what was asked for — a value
that happened to sit right at zetuv's own left-wheel breakaway
threshold, producing unreliable, sometimes-zero motion that looked
like a hardware fault (see the bench log's "combined-drive anomaly"
write-up). The values above are corrected to genuine 15%/5%; not
independently re-verified on tovez's own hardware this ticket (no
access to that bench), but the unit convention is a property of the
native binding/vendored kernel shared by every robot, not
robot-specific.

The `left_port`/`right_port`/`fwd_sign_*` values above are tovez's own
wiring fix from `data/tovez.json`'s `motors` group (`left_port: 2,
right_port: 1, fwd_sign_left: -1, fwd_sign_right: 1` — note this is
tovez's own sign convention, not gopiv's, per that file's own
`_port_note`). `full_duty_velocity=7.837` is `travel_calib`×10 from
that same file (`travel_calib_left`/`travel_calib_right` = 0.7837).
`max_duty=15.0` here is a conservative bench-testing value for the
*first* pulse — raise it once motion direction/sign is confirmed sane.
(For the real per-robot config-driven values, `diffdrive_configure_kwargs()`
in `src/config.py` computes exactly this dict from
`config.load_robot_config()` — `boot.py` already runs this exact
composition automatically at power-on (A.3), so a freshly-booted device
with `/robot.json` present has already been configured/begun/started
before you ever open a REPL; the manual commands below are still useful
as a from-scratch REPL-only smoke test that deliberately bypasses
config.py/boot.py, e.g. after a bare `diffdrive.estop()` or to try
values other than the baked config's own. The values above are
hand-derived from `data/tovez.json` for this first manual check.)

**Expected observation**: both wheels turn slowly and briefly (the
`driveDuty` call's 200 ms lease), then stop on their own. Confirm
`diffdrive.output()["cycleCount"]` is advancing while the pulse runs
and `diffdrive.output()["appliedDutyLeft"/"appliedDutyRight"]` (or the
equivalent fields in the returned dict) go to 0 after the lease
expires.

**Once direction and stop are confirmed**: escalate duty/lease
gradually (per PLAN.md's verification note: smallest-visible-pulse
first), and confirm **encoder counts advance with the correct sign**
per wheel — `diffdrive.output()`'s per-wheel position fields, read
independently of the REPL command that issued the drive (i.e. via a
transport other than the one that issued the command, e.g. a `rogo
repl ... ping`/`STATUS` read over the radio transport A.3's boot
wiring already registers — for this REPL-only step, reading `output()`
right after the drive call from the same session is the practical
minimum).
**Explicit stop-verify**: after the lease expires, re-read
`diffdrive.output()`'s position fields twice, 2 s apart, and confirm
Δposition = 0 both wheels.

**What failure looks like**: a wheel spins the wrong direction (sign
error — check `fwd_sign_left`/`fwd_sign_right` against `data/tovez.json`
before assuming a wiring fault); a wheel does not move at all
(`diffdrive.output()["connectedLeft"/"connectedRight"]` false — bus
fault, or `configure()` returned something other than `"ok"` — check
`diffdrive.lastError()`); wheels do not stop at lease expiry (this is
the M1 gate's own hard failure — stop the bench and escalate, do not
continue to step A.5's stall tests with a kernel that already isn't
enforcing lease expiry correctly).

### A.5 Step 2 — Watchdog/lease/reset safety triple

Three sub-cases, run in order, per PLAN.md's M1 gate leg (3) and spec
§7.2 ("Starvation is a control gap; the realistic trigger is polling"):

**2a. Busy-wait stall.**

```python
diffdrive.driveDuty(0.10, 0.10, 5000)   # near-ceiling lease so the stall, not expiry, is what stops it
while True:
    pass
```

Never reaches `microbit_hal_idle()`; `Output.cycleCount` stops
advancing. **Expected**: wheels stop within **≤300 ms** of the stall
starting (`native/watchdog.h`'s `kStallThresholdUs` = 250 000 µs stall
threshold + zero-write time). The LED matrix shows a fixed diagonal-X
fault pattern (`native/watchdog.cpp`). Recover by pressing the reset
button (the REPL itself is unresponsive — this loop never yields to
it).

**What failure looks like**: wheels keep turning past 300 ms, or the
LED matrix shows nothing — either is the M1 gate's hard failure case;
stop and escalate, do not proceed to 2b/2c.

**2b. Polling-idiom stall** — the realistic trigger, not just the
pathological one (spec §7.2: `docs/nezha-upy-review.md` §2). After
recovering from 2a (reset, reconnect, re-run A.4's configure/begin/
start):

```python
diffdrive.driveDuty(0.10, 0.10, 5000)
import radio
radio.on()
while True:
    p = radio.receive()
```

`radio.receive()` returns immediately and allocates every call; this
loop *also* never reaches `microbit_hal_idle()`. **Expected**:
identical outcome to 2a — wheels stop ≤300 ms, fault flag latched, LED
diagonal-X shown. This is the same mechanism as 2a (`Watchdog::poll()`
has no branch on *how* the stall happened, only on *whether*
`cycleCount` has advanced) — confirming both shapes trip identically is
the point of running both, not just one.

**What failure looks like**: same as 2a. If 2a passed but 2b does not,
that is itself a significant finding — it means the watchdog's own
design claim (`native/README.md`: "both M1 safety-case shapes are
covered by the same mechanism, with no special-casing between them")
does not hold in practice; escalate rather than treating 2a alone as
sufficient M1 evidence.

**2c. Reset mid-drive → boot zero-write.** After recovering from 2b:

```python
diffdrive.driveDuty(0.10, 0.10, 5000)
# while wheels are visibly moving, press the physical reset button
```

**Expected**: on reboot, wheels are silent immediately — the Nezha
brick latches its last commanded speed across an nRF52 reset, so
`moddiffdrive_boot_zero_write()` runs from `main.c` before `gc_init()`/
`mp_init()`, before any Python (including student boot code) can run,
sweeping ports 1–4 unconditionally. Confirm silence holds through the
~5 s post-flash-equivalent settle and stays silent — no re-latching.

**What failure looks like**: any wheel motion after reset, however
brief — this is a hard M1 gate case; `docs/design/usecases.md` UC-005's
own error-flows line is explicit: "none tolerated."

### A.6 Step 3 — `rogo repl <robot> ping` through the relay, unchanged host tooling

**Preconditions**: none beyond A.2's fixture (`/robot.json` present,
power-on-and-settle done) — the v5 engine with a radio transport
registered is already running by the time you reach this step, per
A.3's boot wiring; relay running on the host per radio-robot's own
bench conventions; robot JSON channel matches A.2 (3).

**Command** (run from the host, in radio-robot, completely unchanged
tooling): `rogo repl tovez ping`

**Expected observation**: the ping is acknowledged (`_dispatch_cleartext`
in `src/comms.py` answers `PONG:t=<now>` for the `PING` verb); the USB
REPL on the device stays interactive throughout (the scheduled-pump
plumbing means the wire dispatch never blocks the foreground REPL).

**What failure looks like**: no response — check the relay is actually
forwarding to channel 3, group 10; check the device-side transport was
actually registered (`comms.add_transport(...)` returned `True`); a
malformed-count uptick with no reply at all typically means the verb
lookup failed (unexpected line framing) rather than a radio problem.

### A.7 Step 4 — `wifi_bench_gate.py --port wifi: --skip-drive` 9/9

**Preconditions**: A.2's WiFi power-cycle discipline done *first*;
`wifi_secrets.json` present **on the device filesystem** at bench time
(gitignored, per CLAUDE.md — this is the on-device copy `boot.py`'s
own step 3 checks for, distinct from a local copy on your dev machine).
Its presence at power-on is what `boot.py` uses to decide whether to
register a `wifi_at.WifiAtLink` transport on the UDP v5 plane at all
(A.3) — no separate registration step is needed here. `WifiAtLink`'s
own single-context-module-access discipline
(`service()`/the module-level `pump()` called only from the scheduled-
pump context, never an IRQ/VM hook) is what `boot.py`'s `_BootPumpTimer`
composes on top of `comms.PumpTimer`'s own tick.

**Command** (host tooling, radio-robot): `wifi_bench_gate.py --port
wifi: --skip-drive`, with a live `nc` REPL session (the TCP stdio-REPL
mirror on :7654) held open **throughout** the gate run — this is
deliberately concurrent load on the same WiFi module, not a
before/after check.

**Expected observation**: 9/9. The held-open `nc` session stays
interactive the whole time (concurrent TCP REPL + UDP v5 traffic on one
module, per spec's "proven dual-plane" decision).

**What failure looks like**: fewer than 9/9 — check the power-cycle was
actually done (stale AT state from a prior session is the #1 landmine-
ledger cause here); a per-character AT send pattern in a packet capture
would indicate a coalescing regression (should never happen — one
`CIPSEND` per datagram is a tested invariant of `tests/test_wifi_at.py`,
but that test is offline/mocked, so a live divergence is worth
capturing precisely if seen).

### A.8 Step 5 — `move_protocol_bench.py` full pass over the radio path

**Preconditions**: A.6's radio path already confirmed live. `boot.py`
already wires `motion.RobotDispatch` (a real `motion.MoveQueue(diffdrive)`
+ `config.ConfigDispatch`) as `comms.Comms`'s dispatch whenever
`/robot.json` loaded successfully (A.3), so MOVE/WHEELS/STOP/ESTOP/
GO_TO/CALIBRATE verbs already reach the kernel — falling through to
`NullDispatch` at this point in the ladder would mean `/robot.json` was
missing or invalid; re-check A.2's fixture step if this stage's motion
commands ack but nothing moves.

**Command** (host tooling, radio-robot): `move_protocol_bench.py`, full
pass, over the radio path (not WiFi — this is the primary-transport
gate).

**Expected observation**: full pass; OTOS pose sane in telemetry
(`telemetry.py`'s `otos` field, non-garbage x/y/heading once the
sensor's own 0x17 init has completed).

**What failure looks like**: queued moves not advancing —
`MoveQueue.tick()` needs the scheduled pump running every cycle to
renew leases and detect timeout faults (`TIMEOUT_GRACE_MS = 250`, the
same 250 ms threshold as the watchdog's own stall window, deliberately
shared rather than a second invented constant); a stalled pump reads as
every queued move eventually timeout-faulting, not as "nothing
happens."

### A.9 Step 6 — the M6 sweep

Five checks, all on the same `--clean` image from A.2 (no new code —
per PLAN.md/spec, M6 is acceptance only):

1. **Quiet-host kill test**: issue a drive/move command, then stop
   sending anything from the host entirely (do not send STOP — just go
   quiet). **Expected**: the lease itself expires (see Part B §B.3 for
   the ceiling) and wheels stop on schedule, with no watchdog fault
   latched (this is ordinary lease expiry, not a stall — the two are
   different code paths and both should be distinguishable in
   `output()`/telemetry afterward).
2. **Power-cycle boot-zero test**: same as A.5's 2c, but via a full
   power-cycle (not just the reset button) — confirms the boot
   zero-write path survives a cold boot, not just a soft reset.
3. **10-minute dual-plane soak**: drive commands and telemetry flowing
   concurrently over radio *and* WiFi UDP for 10 minutes continuous.
   **Expected**: no divergence between the two planes' view of state,
   no AT-module lockup, no growing `malformed_count`/dropped-command
   count on either transport.
4. **RAM/flash checkpoint**: run `./build.sh --clean --with-diffdrive
   --with-wifi` again and read its own `arm-none-eabi-size` tail
   output. **Compare against ticket 007's recorded baseline** — the
   frozen-manifest numbers from this repo's last M5 build: `text=333212
   data=8 bss=126992`; `addlayouttable.py`'s layout places MicroPython
   at `0x00000..0x5159c`, the layout table at `0x51fd0..0x52000`, the
   filesystem at `0x6d000..0x73000` — flash end (`0x5159c`) well under
   `_fs_start` (`0x6D000`). **Note on the "pre-freeze vs post-freeze
   delta" this checkpoint is specified against** (PLAN.md/spec §7.4,
   §9): ticket 007's own completion notes flag that the true pre-freeze
   baseline (from ticket 006, before the `manifest.py` freeze switch)
   was **not independently captured** — it was overwritten by ticket
   007's own `--clean` run before anyone read it. Ticket 007's
   post-freeze numbers above are therefore the *first* real baseline
   this repo has, not one half of a measured delta. This step's actual
   job at M6 is: confirm a from-scratch `--clean` rebuild reproduces
   those same numbers (regression check — a real memory/flash *delta*
   only becomes computable from here forward, against this baseline, on
   whatever future rebuild is being checkpointed next).
5. **`git diff master -- src/firm` = diffdrive-only**: this check runs
   in **radio-robot**, not this repo — this repo has no `src/firm`
   directory at all (that path only exists in radio-robot, where the
   old C++ firmware was hard-cutover-frozen per PLAN.md/spec §2). It
   confirms radio-robot's own `src/firm` tree only changed inside
   `diffdrive/` (the vendored kernel's source) since this project's
   `master`, i.e. nothing else in the old firmware silently drifted
   while this rebuild was underway. Run it from a radio-robot checkout,
   not from `nezha-upy`; it is explicitly **out of this repo's own
   gate**.

**What failure looks like, overall**: any of the five checks failing
means the M6 sweep does not close — file an issue and reopen the
relevant milestone (`docs/design/usecases.md` UC-014's own error flow:
"any failure → issue filed, milestone reopened"), rather than
partially accepting the sweep.

---

## Part B — Student-facing API contract

Spec §7.2 / open item 4 ("decide before M5"). This section restates,
for a reader who did not read `src/motion.py`'s own docstring, the
contract that governs writing MicroPython on this robot. The
authoritative version — including the full loop-ownership reasoning —
lives in `src/motion.py`'s module docstring; this section is a
cross-reference and summary, not a fork of it.

### B.1 The mode contract: two ways to move the wheels

The open item above is resolved at the *mechanism* level by sprint 006
(`docs/design/specification.md` §10 item 4): this project ships **two**
ways to drive `diffdrive` from Python, mutually exclusive per boot
(§B.1.3). They are laid out here side by side because the wrong mental
model for one is exactly the failure mode of the other.

**Shared setup, either mode**: `boot.py` runs
`diffdrive.configure(...)` from `/robot.json` automatically at
power-on (Part A §A.3), but deliberately does **not** call
`begin()`/`start()` itself — `src/boot.py`'s own step-2 comment
explains why: doing that under a live kernel fiber before the caller's
own gains are set would orphan it, so boot only stages a valid config
and leaves `begin()`/committing-to-a-mode to the first real motion
consumer. So by the time you get a REPL prompt, `diffdrive` is
configured but neither mode is latched yet — both examples below start
from `diffdrive.begin()` (needed either way) and diverge from there.

#### B.1.1 Background (fiber) mode — wheel control requires reaching idle

**Wheel control requires the Python program to reach idle.** The
vendored `DiffDrive` kernel (`vendor/differential_drive.h`) runs its
own control cadence on a CODAL fiber, completely independent of
Python's call stack. That fiber is only ever scheduled when Python
calls `microbit_hal_idle()` — the *only* safe yield point in this
image (`docs/design/specification.md` §7.1, closed permanently: no
other hook point in VM execution is safe, because MicroPython's own
stack is load-bearing everywhere else a fiber switch could be
attempted).

Concretely: **a tight `while True:` loop that never reaches idle
starves the kernel fiber**, and this includes loops that *look* like
they are doing something useful — `while True: p = radio.receive()`
starves the kernel exactly as effectively as `while True: pass`,
because `radio.receive()` returns immediately without ever giving
control back to the scheduler. This is the "realistic trigger" spec
§7.2 identifies: the natural way a student writes a polling loop is
already the failure mode, not just the pathological busy-wait a
programmer might reach for when deliberately trying to break
something. The zero-only starvation watchdog (§B.2) is the safety
backstop for this case — it is not a substitute for the contract
itself, and it is not a cadence guarantee.

```python
# Background (fiber) mode -- the kernel drives the wheels on its own
# CODAL fiber once you commit to it with start(). diffdrive is already
# configured (boot.py, from /robot.json); begin()/start() are not
# called yet (see "Shared setup" above).
diffdrive.begin()
diffdrive.start()             # latches background mode for the rest of this boot

diffdrive.driveDuty(5.0, 5.0, 500)   # both wheels move -- the kernel fiber paces this on its own

import radio
radio.on()

# WRONG -- starves the kernel fiber. radio.receive() returns
# immediately without ever giving control back to the scheduler, so
# this "looks" non-blocking but is exactly as starving as `while True:
# pass`. Wheel control (and the comms pump that services wire
# commands) stops responding.
while True:
    p = radio.receive()

# RIGHT -- give control back every iteration so the kernel fiber (and
# the comms pump) actually get scheduled. Any call that blocks via
# mp_hal_delay_ms() reaches microbit_hal_idle() -- utime.sleep_ms() is
# the simplest one (the same mechanism the native binding's own
# step-mode Sleeper uses to reach idle during a settle, sprint 006
# Architecture Overview).
import utime
while True:
    p = radio.receive()
    utime.sleep_ms(5)
```

**Resolved loop-ownership decision** (ticket 007, `src/motion.py`'s
module docstring, spec open item 4): this project does **not** ship an
`on_tick()` callback framework. `motion.py` exposes plain, direct
function calls (`MoveQueue.enqueue()`/`stop()`/`estop()`/`go_to()`),
driven either by the wire dispatch path (`RobotDispatch`, the primary
path — see Part A §A.8) or directly from student/REPL code. "Loop
ownership" for wheel motion itself resolves to **the kernel owns
cadence, not Python** — regardless of how student code is shaped. What
*is* framework-owned is the periodic pumping of `MoveQueue.tick()`
(lease renewal, queue advancement, timeout-fault detection), via
`comms.py`'s scheduled pump — the same mechanism that already services
wire commands every cycle.

#### B.1.2 Generator (step-driven) mode — wheels move while you iterate

**Wheels move while you iterate.** Each `next()` on a `motion.py` move
generator runs exactly one `diffdrive.step()` cycle inline, in your own
calling context — no fiber, no fiber switch — and yields
`diffdrive.output()`. Stop iterating and the wheels stop: there is no
background cadence to starve or forget about, because nothing keeps
running once you stop calling `next()` (the lease-decay note below
covers the "stopped without a clean `break`" case). This is the
teachable invariant for this mode, and it is the mirror image of
background mode's contract — background mode fails when your code
*doesn't* yield; generator mode simply stops when your code *doesn't
keep asking for the next cycle*.

Breaking out of the loop stops cleanly: a `break` (or the generator
simply going out of scope) raises `GeneratorExit` inside
`motion.drive()`, which runs its `finally` block — one `neutral()` plus
one landing `step()` so the staged zero actually reaches the bus —
before your code moves on. The same `finally` block runs on normal
completion (the `duration_ms` deadline passing) too.

```python
# Generator (step-driven) mode -- diffdrive is already configured and
# begun (see "Shared setup" above); NOT started -- the first step()
# call, made inside motion.drive() below, latches generator mode for
# the rest of this boot instead.
import motion

for state in motion.drive(diffdrive, v=200.0, twist=0.0, duration_ms=2000):
    print(state["positionLeft"], state["positionRight"])
    if state["positionLeft"] >= 400.0:
        break   # stops cleanly -- the generator's `finally` block lands
                # neutral() + one landing step() before this loop exits
```

`v`/`twist` are `[counts/s]`, matching `diffdrive.drive()`'s own units
(`motion.py` never converts them — same convention `Move` uses for
background mode). `duration_ms` is milliseconds, never seconds, same
landmine-guarded convention as everywhere else in this API (§B.3). The
example values above are illustrative, not yet independently confirmed
on real hardware (that confirmation is ticket 009's job); the *shape*
of the example — the `for state in motion.drive(...): ... break` idiom
— is exact: it was executed, unmodified, against the same
`_StubDiffDrive`/`_FakeClock` fake-diffdrive stub `tests/test_motion.py`
uses, and confirmed to yield 3 states, run exactly 4 `step()` cycles
(3 driving + 1 landing), and call `neutral()` exactly once on `break` —
matching `tests/test_motion.py::test_generator_finally_lands_neutral_on_break`'s
own assertions.

An abandoned generator (stopped iterating without a clean `break` —
an exception elsewhere in your code, or the generator reference simply
dropped) is not left running: each cycle renews a short lease
(`cyclePeriod() * motion.GEN_LEASE_PERIODS`, about 3 cycles) on the
underlying `drive()` call, so the kernel decays it to neutral on its
own within that short window even if your Python never runs another
line. If Python has stalled entirely (never reaching idle at all), the
same zero-only starvation watchdog that backstops background mode
(§B.2) is the fallback — mode-independent, keyed off `Output.cycleCount`
either way.

#### B.1.3 Mutual exclusivity: the mode latch (hard constraint)

**The two modes are mutually exclusive per boot, and this is enforced
at the native layer, not a convention.** Whichever of `start()` or
`step()` (the latter called for you inside `motion.drive()`) is called
*first* wins for the rest of this boot; there is no runtime switch and
no `stop()`-then-restart-in-the-other-mode. The losing entry point
raises `RuntimeError`, by design — this is not a bug to work around:

```python
diffdrive.begin()
diffdrive.start()          # latches BACKGROUND mode

diffdrive.step()
# Traceback (most recent call last):
#   ...
# RuntimeError: step() refused: start() already latched fiber mode this boot
```

```python
diffdrive.begin()
diffdrive.step()           # latches GENERATOR mode

diffdrive.start()
# Traceback (most recent call last):
#   ...
# RuntimeError: start() refused: step() already latched step mode this boot
```

(Exact messages from `native/moddiffdrive.cpp`'s `diffdrive_step_fn`/
`diffdrive_start_fn`.) Pick a mode for the whole boot: if you need to
switch, reset the board. There is no concurrency primitive between the
two callers, and the vendored kernel was never designed for one — see
sprint 006's Architecture "Design Rationale" for why a hard latch was
chosen over an interleaving scheme.

### B.2 The watchdog visibility contract

A silent stop at 250 ms is indistinguishable from a hardware fault to
a student debugging a drive routine — so the starvation watchdog's
response is never silent. This applies to **either** mode from §B.1 —
the watchdog is keyed off `Output.cycleCount` and has no branch on
which mode latched. Generator mode also has a faster, first-line decay
of its own (the short per-cycle lease, §B.1.2) that would normally
retire an abandoned generator before the watchdog's 250 ms threshold
is even reached; the watchdog below is the shared fallback for both
modes, not a generator-mode-specific mechanism:

- **Telemetry**: `telemetry.py`'s frame carries `watchdog_fault`
  (bool) as its own top-level field, *and* folds the same signal into
  the packed `flags` bitfield as `FLAG_WATCHDOG_FAULT = 1 << 9` — so a
  wire client checking either the dedicated field or the flags word
  sees the fault. `cycle_overrun_count` (from `cycleOverrunCount_`,
  surfaced starting at M1 per spec §7.5, not deferred to M5) is the
  companion evidence of cadence loss even before a full stall trips the
  watchdog.
- **Display**: the LED matrix shows a fixed diagonal-X pattern
  (`native/watchdog.cpp`) the moment the watchdog's zero-duty write
  fires — visible without any wire client at all, which matters because
  the whole point of the failure mode is that Python (and therefore any
  Python-mediated telemetry read) may itself be the thing that is
  stuck.
- **The fault latches.** It is a durable signal from the moment it
  trips, not a one-shot event a poller can miss — `output()`'s
  `watchdogFault` field and telemetry's `watchdog_fault` stay true
  until whatever your own robot code does to acknowledge/clear it (see
  `motion.MoveQueue.clear_fault()` for the queue-level fault, a
  distinct concept from the watchdog's own hardware-level latch — do
  not conflate the two when debugging: a `MoveQueue` timeout fault and
  a watchdog trip are different mechanisms with different clear paths).

### B.3 Lease semantics

Every `diffdrive.drive()`/`diffdrive.driveDuty()` call takes a
`lease_ms` argument. Two important facts, both load-bearing (PLAN.md's
landmine ledger L4 — a sec/ms slip once ran wheels unsupervised for
8+ minutes):

- **Units are milliseconds, always** — not seconds, everywhere in this
  API (`lease_ms`, `Move.duration_ms`, `MAX_MOVE_DURATION_MS`,
  `TIMEOUT_GRACE_MS`). There is no seconds-based call anywhere in the
  public surface.
- **5000 ms binding-level ceiling, enforced by rejection, never
  clamping.** `lease_ms > 5000` returns `"refused_lease_ceiling"`
  immediately, without calling into the kernel at all
  (`native/moddiffdrive.cpp`'s `kBindingLeaseMaxMs = 5000`) — a units
  bug is a visibly refused command, not a silently truncated one. This
  is independent of, and far tighter than, the kernel's own
  `DifferentialDrive::kLeaseMax` (3,600,000 ms) — the binding's ceiling
  is the one that actually matters day to day.
- A `lease_ms` is a **duration from now**, not an absolute deadline —
  each call resets it.
- Above the native binding, `motion.py`'s queue layer has its own,
  separate ceiling on a *queued move's* total duration:
  `MAX_MOVE_DURATION_MS = 60000` (60 s) — generous for a classroom
  move, refused (not clamped) at enqueue time if exceeded.
  `DEFAULT_LEASE_MS = 1000` is the per-`tick()` lease renewal a queued
  move uses under the hood, well under the 5000 ms binding ceiling, so
  a queue that stops ticking (student loop stalls) decays to neutral
  quickly via ordinary lease expiry — independent of, and faster than,
  the starvation watchdog's own 250 ms detection.
- Generator mode (§B.1.2) has its own analogous renewal: each
  `next()` inside `motion.drive()` renews the lease on its own
  `diffdrive.drive()` call to `cyclePeriod() * motion.GEN_LEASE_PERIODS`
  (about 3 cycles, ~72 ms at the default 24 ms cycle) — short by
  design, so an abandoned generator's last-commanded lease expires and
  the kernel zeroes it well before the starvation watchdog would ever
  need to act.

### B.4 The public robot API surface, as built

**Directly REPL-callable, always available** (native module, no Python
wiring needed — verified against `native/moddiffdrive_glue.c`'s own
method tables):

```
diffdrive.configure(left_port, right_port, fwd_sign_left=1, fwd_sign_right=1,
                     max_duty=0.0, full_duty_velocity=0.0, cycle_period_ms=24) -> status:str
diffdrive.begin() -> status:str
diffdrive.start() -> status:str        # latches BACKGROUND mode (§B.1.3) -- raises RuntimeError if step() already latched
diffdrive.step() -> None               # latches GENERATOR mode (§B.1.3) -- raises RuntimeError if start() already latched;
                                        # also raises on re-entry while a step is already in flight
diffdrive.cyclePeriod() -> int         # [ms] -- read-only; a CALLABLE, not an attribute
diffdrive.drive(velocity, twist, lease_ms) -> status:str      # [counts/s] [counts/s] [ms]
diffdrive.driveDuty(dutyLeft, dutyRight, lease_ms) -> status:str  # [%] [%] [ms] (0-100; see A.4's own units-correction note)
diffdrive.neutral() -> None
diffdrive.estop() -> None
diffdrive.output() -> dict     # cycle counters, per-wheel position/velocity, applied duty,
                                # ready/estopped/leaseExpired/stallHalted/connected* flags,
                                # watchdogFault/watchdogTripCount
diffdrive.lastError() -> status:str
diffdrive.cycleOverrunCount() -> int

robotio.i2c_xfer(address, write_data=b'', read_len=0, repeated=False,
                  pre_clear=0, post_clear=0) -> status:int | (status:int, data:bytes)
```

Every `status:str` is one of `"ok"`, `"refused_unconfigured"`,
`"refused_not_begun"`, `"refused_estopped"`, `"refused_non_finite"`,
`"cadence_preserved"` (the kernel's own values) or
`"refused_lease_ceiling"` (this binding's own addition, B.3). Refusals
are returned, not raised. Every authority default is fail-closed — a
bare `configure(left_port=2, right_port=1)` with no other arguments
still refuses every drive call until real authority values are
supplied. `configure()` is single-call-scoped this sprint (no live
`reconfigure()` yet — a second `configure()` call is not a supported
runtime reconfiguration path). Full detail, including the boot
zero-write and watchdog internals: `native/README.md`.

**Framework modules** (`src/*.py`, frozen into ROM per B.5 below — not
directly "called" by a student typing at the REPL in the way
`diffdrive.*` is, but importable and usable, and this *is* what a wire
client drives):

- `motion.py` — `Move`, `MoveQueue`, `RobotDispatch` (background mode:
  the queue and dispatch layer backing MOVE/WHEELS/STOP/ESTOP/GO_TO/
  CALIBRATE over the wire, Part A §A.8 — a student could construct a
  `MoveQueue` directly against `diffdrive` from the REPL, but the
  sanctioned, tested path is the wire dispatch one) and `drive()`
  (generator mode, §B.1.2 — the sanctioned student/REPL-driven entry
  point for this mode; there is no wire-dispatch equivalent for it).
- `config.py` — `load_robot_config()`, `wheel_control_to_diffdrive_config()`,
  `diffdrive_configure_kwargs()`, `ConfigDispatch`. Per-robot JSON
  loading (fail-closed), the `wheel_control`→`DiffDrive::Config`
  mapping, and the CONFIG/SET_FIELD/GET_CONFIG wire verbs. No
  on-flash tuning store — baked JSON rules at boot; live CONFIG pushes
  are RAM-only.
- `telemetry.py` — `TelemetryState`, `TelemetryFrameBuilder`. The
  22-field telemetry frame, including `watchdog_fault`/
  `cycle_overrun_count` (B.2).
  `otos.py`/`line.py` — sensor drivers, both routed through
  `robotio.i2c_xfer()` (the one shared I2C ledger — never a direct bus
  access from Python, so per-device timers stay shared with the
  kernel's own traffic).
- `comms.py`/`radio_shim.py`/`wifi_at.py` — the v5 protocol engine, the
  radio transport, and the WiFi AT state machine + UDP v5 plane. These
  are what a wire client (rogo, the relay, the bench-gate scripts)
  actually talks to; `src/boot.py` assembles all three (plus the
  scheduled pump) into a running image automatically at power-on — see
  Part A §A.3.
- `boot.py` (sprint 001 ticket 010) — the frozen boot module that
  performs this assembly: fail-closed config load, `diffdrive.configure()`
  (arming — `begin()`/committing to a mode — is deliberately left to the
  first real motion consumer, §B.1's "Shared setup"), comms/transport/
  dispatch wiring, scheduled-pump start, banner/READY.
  Not directly "called" by a student or a wire client at all — it runs
  once, automatically, before the REPL loop starts. See its own module
  docstring for the full six-step sequence and the grounding evidence
  for why it is a plain frozen module (not a `main.py`).

### B.5 One fact that changes how you iterate

Every module above is **frozen** into ROM via `manifest.py`
(`src/codal_port/Makefile`'s `FROZEN_MANIFEST`), not loaded from the
filesystem — this port's MicroPython build does not define
`MICROPY_PERSISTENT_CODE_LOAD`, so it cannot import `.mpy` from the
filesystem at all (spec §7.4). **A change to any `src/*.py` file needs
a full `./build.sh --clean` + reflash to take effect** — editing the
file alone, or copying it to the device's filesystem, does nothing (the
frozen copy in ROM still wins). The device's small on-flash filesystem
(~30 KB) is reserved for the robot's own JSON config and student code
that is *not* one of the frozen framework modules.

---

## References

- `docs/design/specification.md` — governing spec (§2 stakeholder
  decisions, §6 milestones, §7 review findings, §9 verification).
- `native/README.md` — the full `diffdrive`/`robotio` API and safety
  machinery detail this document summarizes in Part B §B.4.
- `src/motion.py` module docstring — the authoritative loop-ownership
  decision text this document restates in Part B §B.1.
- `clasi/sprints/001-python-first-firmware-image-m0-m6/tickets/done/`
  — tickets 001, 004, 006, 007 for the offline work Part A §A.1 points
  back to.
- `clasi/sprints/006-comment-condensation-main-py-rename-generator-control-loop/`
  — tickets 006 (native `step()`/mode latch), 007 (`motion.py`
  generator), 008 (this document's Part B §B.1 update) for the
  generator/step-driven mode.
- `clasi/issues/tlm-stream-ignores-tlm-off.md` — the known bench-tooling
  defect flagged in Part A §A.2.
