# vevov MicroPython Spike Handoff

## Scope and target

This spike was run against **vevov** only:

- USB port: `/dev/cu.usbmodem2121202`
- DAPLink UID: `9906360200052820b8e12372c44f4f67000000006e052820`

No other attached micro:bit was intentionally flashed. All deploys used the
explicit UID so the wrong bench robot would not get overwritten.

The point of this spike was not to finish the full “MicroPython as the base”
migration. The point was to retire the main technical risks by proving that a
MicroPython-based image can:

1. build on top of `micropython-microbit-v2`,
2. expose real robot hardware through a Python module,
3. command wheels from the USB REPL,
4. read real sensors through the existing firmware drivers,
5. drive the vevov OTOS rig servo through Python PWM, and
6. surface the hard parts clearly enough for the eventual implementation agent.

The result is a working built-in `import robot` module in the custom
MicroPython image, plus a clearer map of what is still only exploratory.

---

## Final proven surface

The final image on vevov exported and successfully loaded these names:

```python
import robot

robot.move(v_x_mm_s, omega_rad_s, distance_mm, timeout_ms)
robot.turn(omega_rad_s, angle_rad, timeout_ms)
robot.go_to(x_mm, y_mm, frame, speed_mm_s, arrive_mm, timeout_ms)
robot.drive(left_pct, right_pct)
robot.move_wheels(left_pct, right_pct, ms)
robot.stop()
robot.encoders()
robot.otos()
robot.line()
robot.color()
robot.servo(port, angle_deg)
```

Notes:

- `frame` accepts `0`/`1` or `"world"`/`"robot"`.
- `move`, `turn`, and `go_to` are still exploratory shims. They are shaped more
  like the real firmware command surface, but they do **not** go through the
  production command plane.
- `drive` and `move_wheels` remain useful low-level bench helpers.

### Final end-to-end bench run that completed on vevov

This exact class of mixed script completed successfully over `mpremote`:

```python
import robot

print('exports', [n for n in dir(robot) if not n.startswith('_')])
print('start_enc', robot.encoders())
print('start_otos', robot.otos())
print('line', robot.line())
print('color', robot.color())
robot.servo(1, 60)
robot.servo(1, 120)
robot.servo(1, 90)
print('after_servo_otos', robot.otos())
print('move', robot.move(40, 0.0, 10, 2000))
print('after_move_enc', robot.encoders())
print('turn', robot.turn(1.2, 0.4, 2000))
print('after_turn_enc', robot.encoders())
print('go_to', robot.go_to(20, 0, 'robot', 50, 5, 2000))
print('after_goto_enc', robot.encoders())
print('final_otos', robot.otos())
robot.stop()
```

Representative output from that run:

```text
exports ['stop', 'drive', 'move', 'turn', 'go_to', 'move_wheels', 'encoders', 'otos', 'line', 'color', 'servo']
start_enc (0, 0)
start_otos (0.0, 0.0, 0.0)
line (44, 48, 250, 243)
color (457, 464, 285, 1187)
after_servo_otos (0.0, 0.0, 0.0)
move (0.305, 7.32, 9.581857e-05)
after_move_enc (295, 0)
turn (-3.05, -65.88001, 0.0005749114)
after_turn_enc (-450, 0)
go_to (-0.61, -27.145, 0.001054004)
after_goto_enc (-27, 0)
final_otos (-0.61, -27.145, 0.001054004)
```

Additional focused probes that completed after the final I2C shim fix:

- `robot.move(40, 0.0, 10, 2000)` returned and `robot.encoders()` reported
  `(5, 283)` in one probe.
- `robot.move_wheels(20, 20, 500)` returned `(828, 889)`, and a follow-up
  `robot.encoders()` returned `(850, 912)`.
- `robot.line()` followed by `robot.move(...)` completed in one script.
- `robot.go_to(20, 0, 'robot', 50, 5, 2000)` returned and a follow-up
  `robot.encoders()` reported `(439, 0)` in one probe.

Interpretation:

- wheel motion from Python is real,
- encoder readback is real,
- OTOS readback is real,
- line and color are real,
- servo PWM on vevov S1 is real,
- the higher-level motion shim is good enough for exploratory bench use,
- but it is **not** yet production-grade navigation.

---

## What changed

### 1. Build-system overlay

Key entrypoint:

- `micropython/build.sh`

That script now:

- overlays the CODAL config used by the spike,
- disables BLE to recover flash/RAM budget,
- reduces the GC heap,
- applies the yield/control-C runtime patch,
- copies the robot bridge sources into `codal_port`,
- patches the MicroPython port Makefile for C++ compilation,
- registers the builtin `robot` module,
- refreshes the manual qstr list every build,
- builds the final `MICROBIT.hex`.

### 2. Robot bridge implementation

Primary files:

- `micropython/modrobot/modrobot.cpp`
- `micropython/modrobot/modrobot_glue.c`

The split matters:

- `modrobot.cpp` owns the C++ implementation.
- `modrobot_glue.c` owns the MicroPython registration macros.

The bridge reuses real firmware drivers directly instead of re-implementing the
robot in Python:

- `src/firm/hardware/nezha/nezha_motor.*`
- `src/firm/hardware/generic/real_otos.*`
- `src/firm/hardware/planetx/line_sensor.*`
- `src/firm/hardware/planetx/color_sensor.*`

Servo control uses the MicroPython/CODAL pin HAL directly because on vevov this
path is plain PWM, not a Nezha-side control protocol.

### 3. Upstream compatibility repair after the firmware merge

The bridge stopped building after the upstream layering rename from
`Platform::I2CBus` to `Hal::I2CBus`.

Fix:

- update the bridge include and inheritance to `hal/i2c_bus.h` and
  `Hal::I2CBus`.

### 4. Nezha jack mapping correction for the servo

Critical bench finding:

- the exploratory servo mapping that treated J1 like P0 was wrong,
- that wrong mapping drove the speaker path,
- the correct Nezha PWM mapping is:
  - J1/S1 -> P1
  - J2/S2 -> P2
  - J3/S3 -> P13
  - J4/S4 -> P15

Authoritative in-repo source used for the correction:

- `src/host/robot_radio/io/cli.py`

After the correction, `robot.servo(1, ...)` reliably hit the actual vevov rig
servo on S1/J1.

---

## Main technical challenges and what they mean

### Challenge 1: the bridge must honor the real I2C bus contract, not just raw reads/writes

This became the most important late-stage discovery.

The first MicroPython-side `Hal::I2CBus` adapter was too naive:

- it ignored `preClear`,
- it treated `postClear` as an inline busy-wait instead of a per-device future
  clearance deadline,
- it did not preserve the production bus contract that `NezhaMotor` and
  `RealOtos` assume.

That broke in subtle ways once mixed traffic happened:

- motion could work in one script and hang in another,
- `move_wheels()` could return but a follow-up `encoders()` call could wedge,
- sensor reads followed by motion were flaky,
- `go_to` and mixed scripts were much less stable than single isolated calls.

Root cause:

- `src/firm/hardware/nezha/nezha_motor.cpp` relies on the concrete bus honoring
  per-device clearance windows across split-phase encoder requests and reads,
- the real implementation is in `src/firm/platform/microbit/microbit_i2c_bus.*`,
  and the spike adapter was not matching it closely enough.

Fix applied in the spike:

- update the MicroPython-side bus shim in `modrobot.cpp` to track per-address
  `lastEnd`/`readyAt`,
- wait on entry according to `max(readyAt, lastEnd + preClear)`,
- update `readyAt = lastEnd + postClear` after each transaction,
- keep a `clearanceSafetyNetCount()` counter.

This was the change that stabilized the final mixed sensor + motion bench runs.

### Challenge 2: C++-backed MicroPython exception paths appear unsafe in this spike shape

Another hard part surfaced during the `go_to` rewrite.

Observed behavior before the final stabilization pass:

- trivial `robot.go_to(0, 0, 'robot', ...)` returned,
- non-trivial `robot.go_to(20, 0, 'robot', ...)` could wedge the REPL,
- even intentionally bad `robot.go_to(...)` argument cases could wedge instead
  of surfacing a clean Python exception.

Practical conclusion from this spike:

- success-path returns were much safer than exception-path exits from this
  built-in C++ bridge shape.

What was done here:

- simplify `go_to` into an exploratory single-pass shim that avoids depending on
  a repeated closed-loop error path,
- keep the bench scenario on the success path,
- document the exception-path fragility instead of pretending it is solved.

What the implementation agent should probably do:

- either move argument/error surfacing into plain C registration wrappers, or
- audit the full C++/MicroPython NLR interaction carefully before relying on
  C++-side `mp_raise_*` behavior in complex paths.

### Challenge 3: the real firmware interface is not the same thing as the exploratory shim

This was a stakeholder correction and it matters.

The original exploratory wheel helper surface (`left_pct`, `right_pct`, `ms`)
was useful for bring-up, but it is **not** the real project command interface.

The real firmware surface already has `Move` and `GoTo` semantics in:

- `src/protos/envelope.proto`
- `src/firm/messages/envelope.h`

That is why the spike bridge was reshaped toward:

- `move(v_x, omega, distance, timeout)`
- `turn(omega, angle, timeout)`
- `go_to(x, y, frame, speed, arrive, timeout)`

Important caveat:

- these are only **API-shaped shims** over exploratory local control logic,
  not the production command plane.

### Challenge 4: Nezha timing and encoder semantics are load-bearing

The Nezha path is not “just write bytes over I2C.”

The working spike depends on preserving real driver behavior:

- duty shaping and write throttling,
- split-phase encoder request/read sequencing,
- settle timing between select and read,
- the concrete motor driver’s own direction and travel calibration behavior.

That is why reusing `Hardware::NezhaMotor` was the right choice.

### Challenge 5: mixed bench validation matters more than isolated one-call demos

A major lesson from this spike is that isolated probes can look fine while the
real “operator workflow” still fails.

The mixed-script case caught bugs that simple one-liners did not:

- sensors plus motion in one REPL script,
- servo plus motion in one REPL script,
- repeated commands without reflashing in between,
- `go_to` after the motion API reshaping.

For this project, the mixed script is the real acceptance test.

---

## Current shape of the motion shim

### `move(v_x_mm_s, omega_rad_s, distance_mm, timeout_ms)`

- Converts the requested twist to wheel duties with a local exploratory
  differential-drive model.
- Uses wheel-position deltas from `NezhaMotor` to decide when the requested
  travel distance has been reached.

### `turn(omega_rad_s, angle_rad, timeout_ms)`

- Commands a differential turn using the same exploratory twist-to-duty logic.
- Uses differential wheel travel to estimate turned angle.

### `go_to(x_mm, y_mm, frame, speed_mm_s, arrive_mm, timeout_ms)`

Current spike behavior:

- resolves `robot` frame targets into world coordinates once at acceptance,
- reads the current OTOS pose,
- turns toward the target heading if needed,
- runs a forward distance segment,
- returns the final OTOS pose tuple.

This is deliberately simpler than the first attempted closed-loop version because
that earlier version exposed the exception/wedge problem and was not reliable
enough for the bench.

This is good enough for a spike. It is not the final navigator.

---

## Build and deploy procedure that worked

From `micropython/`:

```bash
./build.sh --with-modrobot --with-yield
```

That produced:

- `micropython/micropython-microbit-v2/src/MICROBIT.hex`

Deploy to vevov only:

```bash
mbdeploy deploy --hex micropython/micropython-microbit-v2/src/MICROBIT.hex   9906360200052820b8e12372c44f4f67000000006e052820
```

Repeated reality on this bench:

- flashing often first hit an erase/probe failure,
- the automatic mass-erase recovery path succeeded,
- the retry then programmed the board successfully.

USB REPL access:

```bash
mpremote connect /dev/cu.usbmodem2121202
```

---

## Files the next agent should start from

Primary implementation and notes:

- `micropython/vevov-micropython-spike-handoff.md`
- `micropython/build.sh`
- `micropython/modrobot/modrobot.cpp`
- `micropython/modrobot/modrobot_glue.c`
- `src/host/robot_radio/io/cli.py`
- `src/protos/envelope.proto`
- `src/firm/messages/envelope.h`

Supporting port files:

- `micropython/micropython-microbit-v2/src/codal_app/microbithal.cpp`
- `micropython/micropython-microbit-v2/src/codal_app/microbithal.h`
- `micropython/micropython-microbit-v2/src/codal_port/Makefile`
- `micropython/micropython-microbit-v2/src/codal_port/mpconfigport.h`
- `micropython/micropython-microbit-v2/src/codal_port/qstrdefs_robot.h`

Also relevant:

- `clasi/reflections/2026-08-13-firmware-interface-misstatement.md`

---

## Wi-Fi REPL + v5 mode: WORKING on gopiv (2026-08-14)

The Wi-Fi stdio bridge is verified end to end on **gopiv** (module on J1,
DHCP lease 192.168.1.203, TCP server port 7654), fully headless:

```
nc 192.168.1.203 7654          # or any TCP client
>>> print(1+1)                 # normal MicroPython REPL over Wi-Fi
2
>>> import robot
>>> robot.enter_v5()           # hand the socket to the v5 line protocol
[V5 mode] send REPL to exit
PING  -> PONG                  # cleartext verbs + binary TLM: push frames
HELLO -> DEVICE:NEZHA2:MICROPY-WIFI
REPL  -> OK:leaving-v5         # back at the Python prompt
```

Cold boot to serving ≈ 15-35 s. **Connect-retry is required**: the module's
TCP server PERSISTS across nRF resets, so a client that connects while the
bridge is still bringing the link up gets accepted by the module and then
orphaned when configure closes all links. Connect, send `\r\n`, and if
nothing comes back within ~3 s, reconnect and try again.

Four bugs made the previous session conclude "the device is not joining":

1. **`awaitReply()` lost replies the stdio pump had already consumed.**
   `pumpIncoming()` runs at high frequency from `readable()` while the REPL
   idles at its prompt; it eats the module's reply bytes and sets
   `awaitMatched_`, but `awaitReply()` only checked that flag after feeding
   a NEW byte — so the match was discarded and every await timed out. The
   state machine therefore only made progress while Python code was
   *executing* and looped probe→backoff forever when idle or headless —
   i.e. exactly when anyone was watching for the join. Fixed: check the
   flags before pulling bytes.
2. **`sendCommand()` destroyed live client data.** It called
   `uart_.clearRxBuffer()` (and zeroed the stage buffer) before every AT
   command; since each echoed character issues an `AT+CIPSEND`, echoing
   char N of an incoming line nuked chars N+1.. still in the DMA ring
   ("print" arrived as "pint", then the session wedged). Fixed: drain
   through the parser (`pumpIncoming()`) instead of discarding.
3. **Zombie module links broke configure.** The module keeps its server
   and client links across nRF resets; bare `AT+CIPCLOSE` is invalid under
   `CIPMUX=1` (always ERROR), so stale links survived and the non-tolerant
   `AT+CIPMUX=1` failed every cycle. Fixed: close with `AT+CIPCLOSE=5`
   (all mux links) before the strict steps, stop the server first.
4. **stdout dropped whole strings.** A hand edit in the vendored
   `mphalport.cpp` had made `mp_hal_stdout_tx_strn` send `ASYNC` behind
   `isWriteable()`, silently dropping any burst that did not fit the TX
   buffer — which truncated `wifi_status()` output AND broke mpremote's
   raw-REPL handshake (the diagnostic channel died with the patient).
   Fixed: back to `SYNC_SPINWAIT` + the Wi-Fi mirror; `build.sh`'s
   patcher text updated to match. Also: probe window 250 ms → 1000 ms with
   3 attempts per jack (the module answers AT late while auto-rejoining),
   `+IPD` payload is dropped until the bridge itself is `kReady`, and the
   rx ring is flushed on `restart()` — buffered bytes with no live client
   used to busy-spin `mp_hal_stdin_rx_chr` and freeze the state machine.

Debug surface: `robot.wifi_status()` returns one line with
`state=/step=/client=/rx=/ip=/cmd=/reply=` — `reply=` shows the module's
last words, which is what cracked every one of the bugs above.

## SOLVED (2026-08-14): "exception paths wedge the REPL" was the NLR + GCC 15 combo

Challenge 2 above is closed. The wedge was never about the C/C++ boundary:
**raising ANY Python exception HardFaulted the board**, reproduced on an
otherwise stock micropython-microbit-v2 build with zero robot code. This
port pins MicroPython **v1.18**, whose hand-written thumb NLR assembly
(`py/nlr_thumb.c` -- the setjmp-analog behind every `raise`) misbehaves
when built with the bench's **arm-gcc 15.2** toolchain: `nlr.ret_val`
arrived as a constant garbage pointer and the VM faulted in
`mp_obj_exception_add_traceback` (caught with pyocd + gdb on the wedged
board; deterministic across builds). Every "wedge" this spike documented --
bad `go_to` arguments, mpremote raw-REPL failures after errors, sessions
dying on a typo -- was this one defect, invisible because all passing tests
ran success paths only.

Fix: `MICROPY_NLR_SETJMP=1` (newlib's own setjmp/longjmp instead of the
v1.18 asm), applied by `build.sh` Step 3b. Verified on gopiv: `1/0` and
undefined names print clean tracebacks on USB and Wi-Fi; `robot.servo(99,0)`
raises a clean ValueError from C++ (the exact case this handoff said was
unsafe); 20-line output storms and long sessions survive.

Two vevov-era patches were also retired as heap-corruption risks, since no
kernel fiber exists in this build to justify them: the `MICROPY_GC_HOOK_LOOP`
(ran a CODAL event + `schedule()` fiber switch MID-GC-SWEEP) and the
`schedule()` in `microbit_hal_background_processing` (same, from the VM
hook). The Wi-Fi bridge pump/flush now runs only from main-context sites
(`mp_hal_stdin_rx_chr`'s wait loop, `mp_hal_stdio_poll`), and the bridge's
own wait loops busy-poll rather than `schedule()` -- fiber switches from
deep inside the VM's C stack are the same corruption class.

## Transport coexistence: VERIFIED both directions (2026-08-14 evening)

The two Wi-Fi users of the one RJ11-powered module clear each other's
persisted state:

- The MicroPython bridge AT+RSTs the module at bring-up (nothing inherited).
- `Hardware::WifiLink`'s configure tears down the bridge's persisted
  TCP-server/mux state (`CIPMODE=0`, `CIPSERVER=0`, `CIPCLOSE=5`, strict
  `CIPMUX=0`) -- verified adversarially on gopiv: poison the module with the
  MicroPython server, flash standard firmware with NO power cycle,
  `wifi_bench_gate --skip-drive` scores 9/9 (VER confirmed the fix build).

If the module ever goes fully dark (no ping, no server, neither transport
comes up), that is the bring-up kit README's module WEDGE: only a power
cycle of the robot recovers it. Seen once 2026-08-14 after heavy mixed-
transport testing; the power cycle cleared it immediately.

## Recommended next steps for the implementation agent

1. **Keep the build overlay shape.**
   Do not scatter this spike logic into unrelated firmware code.
2. **Keep the C/C++ split for the builtin module.**
   That is the least painful path for this MicroPython port.
3. **Preserve explicit-UID flashing for bench work.**
   Multiple boards on one host is a real hazard.
4. **Keep the corrected Nezha PWM jack mapping.**
   J1/S1 is P1, not P0.
5. **Preserve the real I2C clearance semantics.**
   This is load-bearing for mixed motor/sensor traffic.
6. **Do not treat the exploratory `go_to` shim as a finished navigator.**
   It proves that a Python-facing API with world/robot frames is viable, not
   that the final navigation stack is done.
7. **Investigate exception handling at the C/C++ boundary before productionizing.**
   The bench evidence says success paths are currently safer than raise paths.
8. **Promote the final mixed REPL script into a repeatable regression test.**
   That script caught the real bugs.
