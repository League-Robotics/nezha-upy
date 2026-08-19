# Bench acceptance procedures + student-facing API contract (M6)

Sprint 001, ticket 009. This document is itself a documentation
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
- **Settle**: wait **~5 s** after `mbdeploy` reports success before
  opening a REPL or expecting a radio/WiFi response.
- **WiFi module**: **power-cycle it** before any step that touches the
  WiFi transport (step A.7 below) — its AT state persists across nRF
  reflashes, so a fresh flash of the micro:bit does **not** reset it.

### A.3 Known gap: no on-device boot script ships yet

Flagging this here, once, rather than silently discovering it partway
through the ladder: **this repo does not yet ship a `main.py`/`boot.py`
that assembles the pieces into a running image at power-on.** Each
piece is built and independently tested, but nothing currently wires
them together on the device:

- `config.load_robot_config("/tovez.json")` +
  `config.diffdrive_configure_kwargs(robot_config)` →
  `diffdrive.configure(**kwargs)` (the composition `config.py`'s own
  docstring names as "boot code does...", but no boot code exists in
  this repo yet to do it).
- `comms.PumpTimer.__init__(self, comms, now_fn)`'s own docstring:
  the periodic source that drives `tick()` is "deliberately NOT
  hard-coded to a specific peripheral API here ... whichever a later
  ticket wires up" — no ticket has wired it up yet.
- `motion.RobotDispatch`'s own docstring names it "the single composite
  object wired as `comms.Comms(..., dispatch=...)`" — again, describing
  the intended composition, not a file that performs it.

**Practical effect**: step A.4 (REPL wheel spin) and the busy-wait leg
of step A.5 (safety triple) need only the `diffdrive`/`robotio` native
modules, which are always present — unaffected by this gap. Steps A.6
onward (`rogo repl ... ping` through the relay, `wifi_bench_gate`,
`move_protocol_bench`, the M6 sweep) need the v5 engine
(`comms.Comms` + a transport + a pump) actually running on the device,
which today means typing the composition above at the REPL each bench
session (or writing a bench-local `main.py` on the device filesystem —
the filesystem is reserved for exactly this, per spec §7.4 — which is
outside this doc-only ticket's scope to author). This is flagged, not
fixed, here; it is a reasonable candidate for a follow-on ticket, since
PLAN.md's M3–M6 gates assume an image that reaches this state on its
own.

### A.4 Step 1 — REPL wheel spin (smallest-visible-pulse first)

**Preconditions**: A.2's build+deploy+settle done; USB REPL connected
(e.g. `mpremote connect /dev/<port>`, per the pattern already used
during the prior MicroPython exploration).

**Commands** (typed at the REPL):

```python
import diffdrive
diffdrive.configure(left_port=2, right_port=1,
                     fwd_sign_left=-1, fwd_sign_right=1,
                     max_duty=0.15, full_duty_velocity=7.837,
                     cycle_period_ms=24)
diffdrive.begin()
diffdrive.start()
diffdrive.driveDuty(0.05, 0.05, 200)   # smallest visible pulse: low duty, short lease
```

The `left_port`/`right_port`/`fwd_sign_*` values above are tovez's own
wiring fix from `data/tovez.json`'s `motors` group (`left_port: 2,
right_port: 1, fwd_sign_left: -1, fwd_sign_right: 1` — note this is
tovez's own sign convention, not gopiv's, per that file's own
`_port_note`). `full_duty_velocity=7.837` is `travel_calib`×10 from
that same file (`travel_calib_left`/`travel_calib_right` = 0.7837).
`max_duty=0.15` here is a conservative bench-testing value for the
*first* pulse — raise it once motion direction/sign is confirmed sane.
(For the real per-robot config-driven values, `diffdrive_configure_kwargs()`
in `src/config.py` computes exactly this dict from
`config.load_robot_config()` — see A.3's gap note; the values above are
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
transport other than the one that issued the command, once A.3's
wiring is up — for this REPL-only step, reading `output()` right after
the drive call from the same session is the practical minimum).
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

**Preconditions**: A.3's wiring gap addressed for this session (v5
engine running on the device with a radio transport registered); relay
running on the host per radio-robot's own bench conventions; robot JSON
channel matches A.2 (3).

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
`wifi_secrets.json` present locally (gitignored, per CLAUDE.md); A.3's
wiring extended to also register a `wifi_at.WifiAtLink` transport on
the UDP v5 plane, per `src/wifi_at.py`'s own module docstring (single-
context module access — `WifiAtLink.service()`/the module-level
`pump()` called only from the same scheduled-pump context `comms.py`'s
`PumpTimer` uses, never from an IRQ/VM hook).

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

**Preconditions**: A.6's radio path already confirmed live; A.3's
wiring includes `motion.RobotDispatch` (backed by a real
`motion.MoveQueue(diffdrive)` and `config.ConfigDispatch`) as the
`comms.Comms(..., dispatch=...)` argument, so MOVE/WHEELS/STOP/ESTOP/
GO_TO/CALIBRATE verbs actually reach the kernel rather than falling
through to `NullDispatch`.

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

### B.1 The idle-reaching contract

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
something.

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

A known, explicitly-flagged gap (not built this sprint): a
stakeholder-approved but not-yet-ticketed proposal
(`clasi/issues/generator-driven-control-loop-mode-addition-not-replacement.md`,
status `pending`) would add a *second*, additive execution mode where
move commands are Python generators and each `next()` runs one kernel
step inline. Its prerequisite native bindings do not exist in
`native/moddiffdrive.cpp` today (no `step()` binding) — this is future
work, recorded here so a reader of this contract knows the "no
`on_tick()`" decision is scoped to what actually shipped, not a claim
that no other execution model is ever coming.

### B.2 The watchdog visibility contract

A silent stop at 250 ms is indistinguishable from a hardware fault to
a student debugging a drive routine — so the starvation watchdog's
response is never silent:

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

### B.4 The public robot API surface, as built

**Directly REPL-callable, always available** (native module, no Python
wiring needed — verified against `native/moddiffdrive_glue.c`'s own
method tables):

```
diffdrive.configure(left_port, right_port, fwd_sign_left=1, fwd_sign_right=1,
                     max_duty=0.0, full_duty_velocity=0.0, cycle_period_ms=24) -> status:str
diffdrive.begin() -> status:str
diffdrive.start() -> status:str
diffdrive.drive(velocity, twist, lease_ms) -> status:str      # [counts/s] [counts/s] [ms]
diffdrive.driveDuty(dutyLeft, dutyRight, lease_ms) -> status:str  # [-1,1] [-1,1] [ms]
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

- `motion.py` — `Move`, `MoveQueue`, `RobotDispatch`. The queue and
  dispatch layer backing MOVE/WHEELS/STOP/ESTOP/GO_TO/CALIBRATE over
  the wire (Part A §A.8). A student could construct a `MoveQueue`
  directly against `diffdrive` from the REPL, but the sanctioned,
  tested path is the wire dispatch one.
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
  actually talks to; see Part A §A.3 for the current on-device-wiring
  gap.

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
