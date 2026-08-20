# nezha-upy — Consolidated Specification

Sources: `PLAN.md` (primary, stakeholder decisions 2026-08-18, all
fixed; confirmed governing 2026-08-19), `docs/nezha-upy-review.md`
(architecture review, 2026-08-18), stakeholder directives of
2026-08-19 (issues in `clasi/issues/`). The
`docs/micropython-full-firmware-in-the-image-gates-3-7.md` plan
(2026-08-15) is **superseded as architecture**; its carried-over
constraints appear in §8.

## 1. Mission

MicroPython on micro:bit becomes the base firmware for the Nezha robot.
Everything is Python — drivers, boot, config, telemetry, motion, the v5
protocol engine — **except the differential drive**, which stays the
C++ `DiffDrive` kernel plus its `NezhaMotor` leaf, vendored from
radio-robot.

## 2. Fixed stakeholder decisions (2026-08-18)

| decision | choice |
|---|---|
| v5 wire | byte-for-byte compatible — host tooling + relay unchanged |
| transports | **v5 on radio** (primary); **REPL on USB and WiFi**; WiFi also carries the UDP v5 plane (proven dual-plane) |
| C++ payload | DiffDrive kernel + NezhaMotor leaf + minimal shims — nothing else |
| old firmware | hard cutover: radio-robot `src/firm` (minus `diffdrive/`) frozen |
| location | own repository `League-Robotics/nezha-upy`; kernel + Nezha leaf VENDORED by a sync script from radio-robot (`sync_upy.py`, the `sync_pxt.py` pattern); radio-robot keeps kernel SOURCE and its `src/tests/diffdrive/` gate, plus all host tooling unchanged |
| first robot | gopiv per PLAN.md (motors+encoders+OTOS+line, WiFi module, ran the old MP image); **bench target for this project's acceptance: tovez** (stakeholder 2026-08-19, §9) |

Additional decisions (stakeholder, 2026-08-19):

- **PLAN.md governs.** The full-C++-firmware plan (Gates 3–7 doc) is
  superseded as architecture.
- **Bench:** micro:bit named **tovez**, radio **channel 3**, deploy
  with **`mbdeploy`**. Radio-robot bench conventions apply: deploy by
  UID, `--clean` builds, ~5 s post-flash settle, power-cycle the WiFi
  module before WiFi work.
- **Hardware acceptance is performed by the stakeholder on master.**
  The sprint delivers offline-verified work; hardware gates are
  documented as stakeholder acceptance procedures.
- **Robot configuration data** is copied from
  `/Volumes/Proj/proj/RobotProjects/radio-robot-elite/data/robots`
  (`robot_config.schema.json`, `tovez.json`, `tovez_nocal.json`,
  `gopiv.json`, `togov.json`, `active_robot.json`) to provide
  configuration and test parameters.

## 3. What exploration established (paid-for knowledge)

The old MP worktree (`micropython-vevov-handoff`, 38 commits) is the
launchpad: Gate 2 closed — no-SoftDevice link works, 132 KB flash
headroom, GC heap 40 KB, `DEVICE_BLE:0`. `build.sh` (813 lines, forked
into this repo's root with `codal_overlay.json` + `patches/`) is a
working patch-engine build over vendored `micropython-microbit-v2`
@0697c6d.

Landmine ledger non-negotiables (L1–L9):

- `MICROPY_NLR_SETJMP=1` (GCC15: any exception HardFaults without it).
- Fiber switches from VM/GC hooks **corrupt the heap** — the only safe
  yield is `microbit_hal_idle()` (main context); Python execution never
  happens from a fiber. See §7.1 for the mechanism (question
  permanently closed).
- The WiFi module persists state across nRF reflashes — power-cycle
  first.
- `Wheels.duration`/`Move.time` are **[ms]** — a sec/ms slip once ran
  wheels 8+ minutes; 5000 ms lease ceiling + boot zero-write mandatory.
- Per-char AT sends flood the module — one CIPSEND per datagram.
- build.sh editing ritual: `bash -n`, py_compile heredocs, `--clean`
  before hardware verify.

Verified directly during exploration:

- MP `radio.config` exposes everything the shim needs (length, queue,
  channel, group); `queue=4` fixes the C++ single-slot RX loss.
- `microbit.uart.init(tx,rx)` **retargets the one stdio UART** — the
  WiFi UART must be a tiny UARTE1 C shim (the stock port never exposes
  the second UARTE); the AT state machine on top is Python.

## 4. v5 wire contract

Truth = radio-robot `src/protos/` + `src/firm/core/comms.cpp` +
`telemetry.cpp` (`docs/protocol-v5.md` is stale). Contract:

- COBS keyed 0x0A; CRC-16/CCITT-FALSE over `command+':'+payload`;
  CRC-then-COBS.
- Parse order is load-bearing: relay sigils dropped first; TLM/SEED/DBG
  intercepted before the binary branch; TLM inbound is a cleartext mode
  verb.
- 25 verbs; ack ring depth 12, packed `corr_id<<4|err`, repeats 3.
- Telemetry emit policy default AUTO = silent-while-parked, 25 ms
  period, pending acks force emission; banner byte-frozen.
- `src/host/robot_radio/io/wire_codec.py` (radio-robot) is pure
  MicroPython-clean Python — ports nearly verbatim.
  `tests/fixtures/wire_golden_vectors.txt` (8 cross-language vectors)
  is the acceptance fixture.
- Radio on-air: `[SEQ][FLAGS][LEN]` fragments, MTU 247, group 10;
  fragment reassembly per radio-robot
  `src/firm/platform/microbit/microbit_radio_link.cpp`.

## 5. Architecture

```
                  ┌──────────────────────────────── micro:bit ─┐
 USB serial ──────┤ MicroPython REPL (stock, foreground)       │
 WiFi TCP :7654 ──┤ REPL mirror (C stdio hook, proven pattern) │
                  │                                            │
 WiFi UDP :7654 ──┤──┐                                         │
 radio (v5/relay)─┤──┤→ src/comms.py — Python v5 engine        │
                  │  │   runs as a BOUNDED SCHEDULED PUMP      │
                  │  │   (micropython.schedule off a timer —   │
                  │  │   between-bytecodes, REPL stays live)   │
                  │  │                                         │
                  │  └→ src/: config, telemetry, motion,       │
                  │      otos.py, line.py, wifi_at.py,         │
                  │      radio_shim.py            (all Python) │
                  │                                            │
                  │ native/ (the ONLY C/C++):                  │
                  │   moddiffdrive — DiffDrive kernel (compiled│
                  │   from vendor/) + NezhaMotor leaf +        │
                  │   Clock/Sleeper/Launcher + i2c broker +    │
                  │   UARTE1 pipe + watchdog                   │
                  │   kernel on its own CODAL fiber @24 ms     │
                  └────────────────────────────────────────────┘
```

Load-bearing design points:

- **Kernel on a CODAL fiber** (FiberLauncher→`create_fiber`) + the
  `microbit_hal_idle()` yield patch. The lease watchdog that zeroes
  duty must not depend on Python health. Companion: a **zero-only
  starvation watchdog** in the VM hook (never yields; raw zero write if
  kernel cycles stall >250 ms with wheels commanded). The watchdog must
  be **visible**: fault bit in telemetry + display indication (§7.2).
- **One I2C ledger.** All Python sensor traffic goes through the C
  module's `robotio.i2c_xfer()` so per-device `lastEnd/readyAt` timers
  and the TWIM-errata gap are shared with the kernel's 0x10 traffic.
- **Codec generated, not hand-written**: radio-robot's
  `src/scripts/gen_messages.py` grows `--emit-upy --out <path>` → this
  repo's `src/msgs.py` (third renderer over the same descriptor walk).
  One schema, three targets; the generated file is committed here and
  refreshed by the sync script.
- **Kernel boundary across repos**: radio-robot stays the single
  SOURCE of `diffdrive/`; its `src/scripts/sync_upy.py` copies the
  kernel pair + `nezha_motor.{h,cpp}` + the golden-vector fixture into
  this repo's `vendor/` and regenerates `msgs.py`. This repo never
  edits vendored files — a sync-diff check is its gate.

### Repository layout

```
build.sh  codal_overlay.json  patches/   (forked build machinery)
src/       comms.py wire.py msgs.py config.py telemetry.py motion.py
           otos.py line.py wifi_at.py radio_shim.py
native/    moddiffdrive.cpp glue, i2c broker, UARTE1 pipe, watchdog
vendor/    differential_drive.{h,cpp}, motor_armor.h,
           nezha_motor.{h,cpp}                 (SYNCED, never edited)
tests/     golden vectors copy, CPython loopback engine tests
data/      robot configs (schema + per-robot JSON, from
           radio-robot-elite/data/robots)
```

## 6. Milestones (risk-ordered; each gate is a command)

**M0 — new repo + image boots.** Repo populated; build machinery
forked (done); vendor sync run (done); strip/keep-as-reference the
modrobot exploratory layer (kept under `reference/`); secrets
gitignored. *Gate:* `./build.sh --clean` → hex; flash; USB REPL
answers; flash end < `_fs_start` (0x6D000).

**M1 — moddiffdrive: wheels from the REPL.** `native/`:
`moddiffdrive.cpp` + `_glue.c` + manual qstrs (the proven two-file
pattern); NezhaMotor leaf compiled from vendor (anti-latch shaping is
not re-derived); kernel leaves (Clock/Sleeper/Launcher); i2c broker;
boot zero-write before the VM starts; VM-hook watchdog; 5000 ms lease
ceiling in the binding. Python API: `diffdrive.configure/begin/start/
drive/driveDuty/neutral/estop/output/lastError`. Land the wiring fix in
config data (`left_port: 2, right_port: 1`). Surface
`cycleOverrunCount_` in telemetry from M1 (§7.5). *Gate:* (1)
radio-robot's `uv run python -m pytest src/tests/diffdrive/` still
green and the vendored copy sync-diff clean; (2) on the bench robot:
`drive()` with a 1000 ms lease → motion, zero at expiry, counts advance
with the right signs; (3) safety: `drive()` then `while True: pass` →
watchdog zeroes ≤300 ms; **also the polling idiom** `while True: p =
radio.receive()` (§7.2); reset mid-drive → boot zero-write silences.
**Highest-risk milestone; nothing proceeds until it scores.** Hardware
legs of this gate are stakeholder acceptance (§9).

**M2 — wire codec offline.** `src/wire.py` (port of wire_codec.py) +
generated `src/msgs.py`. *Gate:* `tests/` golden-vector suite → 8/8
against the fixture; encode↔decode round-trip against the host pb2 for
every binary verb; `mpy-cross` compiles every `src/*.py` — **as a lint
only** (§7.4: this port cannot load `.mpy` from filesystem; module
shipping is via `manifest.py` freezing, decided at M5).

**M3 — v5 engine + radio (the primary transport).** `src/comms.py`
mirrors `dispatchLine()` order byte-for-byte; ack ring; telemetry emit
policy; banner/boot/READY sequence; the **scheduled-pump plumbing**
(timer → `micropython.schedule(pump)`, bounded work per call, stdin-wait
patch so pending callbacks run while the REPL blocks; pump budget sized
against ~14 ms available per cycle, §7.5). `src/radio_shim.py` over MP
`radio` (`length=250, queue=4, channel=<json>, group=10`), fragment
reassembly per `microbit_radio_link.cpp`, feeding the engine. *Gate:*
offline first — comms.py under CPython + loopback vs the host's own
client, banner/ack byte-exact; then hardware (stakeholder): `rogo repl
<robot> ping` **through the relay, unchanged tooling**; WHEELS over
radio → motion + acks; REPL on USB stays interactive throughout.

**M4 — WiFi: REPL mirror + UDP v5 plane.** C: UARTE1 byte-pipe shim +
the stdio TCP-REPL hook (reuse the proven `wifi_stdio.cpp` core,
pattern reference in `reference/modrobot/`). Python: `wifi_at.py` AT
state machine (CIPMUX=1, UDP :7654, per-datagram coalescing, ≥50 ms TLM
throttle on this plane). *Gate:* `wifi_bench_gate.py --port wifi:
--skip-drive` 9/9 with an `nc` REPL session held open (stakeholder);
power-cycle discipline in the bench notes.

**M5 — full Python firmware layer.** `config.py` (per-robot JSON
on-device, fail-closed key check; `wheel_control`→`DiffDrive::Config`
via travel_calib×10; CONFIG/SET_FIELD/GET_CONFIG live), `otos.py`,
`line.py` (bus facts as captured — 0x17 init/scales/20 ms, 0x1A ×4/
50 ms), `telemetry.py` full 22 fields, `motion.py` (move queue 5-deep,
stop conditions, timeout fault, replace, GO_TO, SEED/POSE, CALIBRATE —
every duration [ms]). Freezing decision lands here: develop on the
filesystem, freeze via `manifest.py` at M5 stabilisation (§7.4).
*Gate:* `move_protocol_bench.py` full pass over the radio path
(stakeholder); OTOS pose sane in TLM; fail-closed boot test.

**M6 — acceptance sweep on the bench robot.** No new code. `--clean`
rebuild; `wifi_bench_gate` 9/9; `move_protocol_bench` full; quiet-host
kill test (lease stops wheels); power-cycle boot-zero test; 10-min
dual-plane soak; RAM/flash checkpoint (measure frozen-manifest heap
delta, §7.4); radio-robot `git diff master -- src/firm` =
diffdrive-only. Stakeholder-executed (§9).

**M7 (later) — additional robots:** color driver (0x43/0x39),
`radio_bench_gate.py` over getez, per-robot JSON.

## 7. Architecture review findings (2026-08-18, incorporated)

### 7.1 Heap-corruption mechanism — hook question permanently CLOSED

CODAL fibers share one physical stack; `codal::schedule()` memcpys
stack regions in/out, and `verify_stack_size()` calls `free`/`malloc`
**inside the context switch**. Consequences: GC-hook fiber switches
replace the bytes under `gc_collect()`'s conservative stack scan (roots
missed, live objects swept, fault surfaces later — matches the observed
`mp_obj_exception_add_traceback` HardFault, gopiv 2026-08-14); the VM
hook has the same class of hazard (`nlr_top` chain is stack-resident;
`MICROPY_NLR_SETJMP=1` does not change that). There is no point inside
VM execution where MicroPython's stack is not load-bearing.
`microbit_hal_idle()` at main context is the only safe yield and always
will be. Any future "try hooking somewhere better" investigation is
dead on arrival — recorded as closed, not deferred.

### 7.2 Starvation is a control gap; the realistic trigger is polling

The zero-only watchdog is a correct **safety** response, not a cadence
guarantee: the kernel fiber advances only when Python reaches
`microbit_hal_idle()`, so 24 ms is cooperative, not real-time. The
realistic trigger is the natural polling idiom (`while True: p =
radio.receive()` — returns immediately, allocates every call, never
reaches idle), not the pathological busy-wait. Requirements:

- The polling loop is a **second M1 safety case** alongside the
  busy-wait.
- The watchdog must be **visible**: fault bit in telemetry (TLM carries
  22 fields) and a display indication — a silent stop at 250 ms is
  indistinguishable from a hardware fault to a student.
- The student-facing API docs must state the contract explicitly: wheel
  control requires reaching idle. Whether the teaching framework owns
  the loop (`on_tick()` callbacks vs student `while True:`) is decided
  before M5.

### 7.3 The exit from the fiber, if M1's safety gate reads badly

`differential_drive.h` documents `FiberLauncher` as optional — a host
driving `step()` itself is a sanctioned composition. The obstacle is
that `step()` blocks (~9–10 ms of the 24 ms cycle: two
`sleepMillis(kSettle=4)` settles plus bus time). The prepared exit:
restructure `step()` into a re-entrant non-blocking state machine
(each settle becomes "return, re-enter no sooner than 4 ms") driven
from a pended low-priority SWI off the system timer — no fiber, no
stack copy, no malloc in a switch, no MicroPython-heap contact (state
in a plain C struct behind a seqlock: writer bumps seq odd→write→even;
reader samples/copies/resamples). `dt` is already measured per cycle
(`measuredPeriodUs`) and pacing is absolute-deadline, so variable
re-entry costs nothing; `kMaxSampleAge` (200 ms) unaffected; Nezha bus
transactions (a few hundred µs) are acceptable in a pended SWI. This is
a `vendor/` change, so it happens in radio-robot under
`src/tests/diffdrive/`. **Sequencing:** build M1 as planned; score the
safety triple; decide from evidence.

### 7.4 `.mpy` cannot be loaded by this port — freeze via manifest

`micropython-microbit-v2` does not define
`MICROPY_PERSISTENT_CODE_LOAD` (upstream default 0): the board cannot
import `.mpy` from the filesystem. The M2 mpy-cross gate is therefore a
**syntax lint**, and is labelled as such. Module shipping is
`manifest.py` freezing (`src/codal_port/Makefile` already sets
`FROZEN_MANIFEST ?= manifest.py`): frozen bytecode executes from ROM.
Given `MICROBIT_HEAP_SIZE` is cut to 40 KB (`codal_overlay.json`) to
buy CODAL ~24 KB, freeze everything; reserve the ~30 KB filesystem for
the robot JSON and student code. Tradeoff: freezing means firmware
rebuild+reflash per Python change — so develop on the filesystem during
M3–M5, freeze at M5 stabilisation, measure the heap delta at the M6
RAM/flash checkpoint.

### 7.5 Smaller review notes (binding)

- The real occupied cycle is ~10 ms, not the documented
  `>= 2*kSettle + margin`; size the M3 comms pump budget against
  **~14 ms** of available window per cycle, not 24.
- **`cycleOverrunCount_` is surfaced in telemetry from M1**, not M5 —
  it is the only direct evidence of cadence loss, needed during the
  risky milestone.

## 8. Constraints carried over from the superseded Gates 3–7 plan

- v5-over-USB EXCLUDED (REPL owns USB; wire clients use radio/WiFi).
- Config persistence: baked JSON rules at boot; live CONFIG pushes
  work; no on-flash tuning store.
- Watchdog: zero duty write retry ×2, latch a flag (now also visible,
  §7.2).
- gopiv true wiring: `left_port: 2, right_port: 1, fwd_sign_left: +1,
  fwd_sign_right: -1` (per gopiv.json `_port_note`) — lands in config
  data.
- WiFi AT discipline: single-context module access; one CIPSEND per
  datagram; ≥50 ms TLM throttle on the WiFi plane; READY on
  new-peer edge handled in the pump.

## 9. Verification & process

- **Offline before hardware, always**: golden vectors (8/8), CPython
  loopback engine tests, mpy-cross compile (lint) of all Python,
  fragment codec vs captured on-air bytes, `./build.sh --clean` → hex
  with flash end < `_fs_start`.
- **Existing suites untouched and green**: radio-robot
  `src/tests/diffdrive/` (the kernel's own gate) and host unit suites
  remain green in radio-robot; this repo's gate is vendor sync-diff
  cleanliness.
- **Hardware ladder** (each step after `--clean` + ~5 s post-flash
  settle): REPL wheel spin → watchdog/lease/reset safety triple →
  `rogo repl <robot> ping` via relay with unchanged tooling →
  `wifi_bench_gate` 9/9 → `move_protocol_bench` full → M6 sweep.
  Smallest-visible-pulse first; encoder delta read from the other
  plane; explicit stop-verify (Δenc = 0 over 2 s). Deploy by UID only;
  module power-cycle before WiFi work.
- **Bench (stakeholder 2026-08-19):** micro:bit **tovez**, radio
  **channel 3**, deploy with **`mbdeploy`**. The stakeholder performs
  hardware acceptance on master; development work is verified offline.

## 10. Open items (non-blocking, decide during execution)

1. `VER`/`ID` strings: format frozen; the version value will identify
   the upy build — flag if any host tool pins the old value.
2. Bench-day check: physically confirm the bench robot's motors/OTOS/
   line before scoring M1 hardware legs; config data carries the
   wiring fix.
3. Radio-robot-side pieces (`sync_upy.py`, `gen_messages.py
   --emit-upy`) are small OOP changes in radio-robot, outside this
   repo's sprint scope; this repo consumes their output. Until the
   codegen lands, `src/msgs.py` may be hand-seeded to the descriptor
   walk with a `GENERATED — do not edit` header and replaced by the
   generator.
4. Teaching-framework loop ownership (`on_tick()` vs student
   `while True:`) — decide before M5 (§7.2). **Resolved at the
   mechanism level, sprint 006** (`docs/bench-acceptance-procedures.md`
   Part B §B.1, `src/motion.py`): neither `on_tick()` nor a raw student
   `while True:`. Framework-owned cadence now lives inside the move
   handle itself (`motion.drive()` returns a `MoveHandle`, ticket 007 /
   ticket 012) — each `next()` runs one kernel cycle and the student's
   own loop body runs between `next()` calls — while the pre-existing
   background/fiber mode is unchanged and still requires the student's
   code to reach idle. The two modes are additive and mutually
   exclusive per boot (native mode latch, ticket 006), not a
   replacement of one by the other. Stopping a generator-mode move is
   **explicit** — `move.stop()`, or `with motion.drive(...) as move:`
   (ticket 012) — not a bare `break`: ticket 009's bench run measured
   that MicroPython's GC does not promptly close a suspended generator
   on `break` alone the way CPython's refcounting does, so `finally`
   would not run and the wheels would keep the last commanded duty
   until the ~250 ms starvation watchdog failsafe caught it. **Still
   open**: which mode is the *primary* teaching posture (background vs.
   generator) is explicitly deferred, not decided here — that call
   belongs to ticket 009's re-run, from bench hardware evidence (the
   safety triple plus a generator-mode drive/`stop()`-or-`with`/
   abandoned-generator leg — `break` alone is not the tested contract).
   Ticket 009 itself is parked, not yet run, pending both this ticket
   and ticket 011 landing and the stakeholder resolving which robot is
   the confirmed bench target (two boards on the bench currently
   self-identify as `tovez`; `zetuv`'s UID has never enumerated —
   sprint 006 `sprint.md`'s Migration Concerns) — so the primary-posture
   question has a named precondition, not a scheduled resolution date.
