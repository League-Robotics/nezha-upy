# nezha-upy — architecture review

**Repo:** `League-Robotics/nezha-upy` @ HEAD (2026-08-18)
**Scope:** PLAN.md, `patches/`, `codal_overlay.json`, `vendor/differential_drive.{h,cpp}`, `vendor/nezha_motor.{h,cpp}`, against upstream `micropython-microbit-v2` and `codal-core`
**Verdict:** the plan is sound and the landmine ledger is accurate. Three findings below change the reasoning under an existing decision, identify an unmitigated failure mode, and correct a gate.

---

## 1. The heap-corruption landmine: mechanism, and why it forecloses future hook-hunting

**Status:** your conclusion is correct. The stated reason is incomplete in a way that matters.

`patches/apply_yield.py` records that fiber switches from the VM and GC hooks corrupt the heap, attributed to running "mid-GC-sweep." The actual mechanism is structural to CODAL and independent of sweep timing.

CODAL fibers do not have separate stacks. Every fiber executes on the same physical stack; `codal::schedule()` memcpys the used region out to a heap buffer and copies the incoming fiber's region back in. From `codal-core/source/core/CodalFiber.cpp`:

- `verify_stack_size(Fiber *f)` computes stack depth against the buffer size and, when short, calls `free()` on the old buffer and `malloc()` for a new one — **inside the context switch**.
- That function contains a comment noting it must fix up `currentFiber` before allocating, "otherwise an external memory allocator might get confused when scanning fiber stacks." Lancaster hit this exact hazard class and patched their own instance of it.

Consequences for MicroPython:

1. **GC hook.** `gc_collect()` conservatively scans the C stack for roots. A fiber switch during that scan replaces the bytes under the scanner with another fiber's stack contents. Roots are missed, live objects are swept, and the fault surfaces later at an unrelated site — matching the observed `mp_obj_exception_add_traceback` HardFault (gopiv, 2026-08-14) rather than crashing at the hook.
2. **VM hook.** Less immediately fatal but the same class: MicroPython's `nlr_top` and its NLR chain are stack-resident, and `MICROPY_NLR_SETJMP=1` (already a non-negotiable in the ledger) does not change that.
3. **Allocation during switch.** `malloc`/`free` from a context that assumed no allocation.

**Implication.** There is no point inside VM execution where MicroPython's stack is not load-bearing. `microbit_hal_idle()` at main context is the only safe yield and always will be. Any future "try hooking somewhere better" investigation is dead on arrival; record it as closed rather than deferred.

---

## 2. The starvation hole is a control gap, and the documented trigger is the wrong one

**Status:** unmitigated for control; mitigated for safety only.

PLAN.md's zero-only starvation watchdog (VM hook, never yields, raw zero write if kernel cycles stall > 250 ms with wheels commanded) is a correct safety response. It is not a cadence guarantee. The kernel fiber advances only when Python reaches `microbit_hal_idle()`, so 24 ms is a cooperative target, not a real-time one.

The trigger documented in the M1 gate — `drive()` then `while True: pass` — is a pathological case. The realistic one is the natural polling idiom:

```python
while True:
    p = radio.receive()
    if p:
        handle(p)
```

`radio.receive()` returns immediately, allocates on every call, and never reaches idle. Same shape for any sensor-poll or line-follow loop a student writes. This will occur routinely, not exceptionally.

**Recommendations:**

- Add the polling loop as a second M1 safety case alongside the busy-wait. They exercise the same path but the polling case is the one that ships.
- Make the watchdog **visible**, not just safe. A silent stop at 250 ms is indistinguishable from a hardware fault to a student debugging a drive routine. Set a fault bit in telemetry (TLM already carries 22 fields) and put something on the display. Without this the failure mode is a support burden, not a bug report.
- Frame the contract explicitly in the student-facing API docs: wheel control requires reaching idle. If the teaching framework owns the loop (`on_tick()` callbacks rather than student `while True:`), the exposure mostly disappears — worth deciding before M5 rather than after.

---

## 3. The exit from the fiber, if M1's safety gate reads badly

**Status:** available, already anticipated by the kernel's own design, blocked only by two calls.

`differential_drive.h` documents `FiberLauncher` as optional: *"A host that drives step() itself should implement this to FAIL LOUDLY — start() being called at all then signals a miswired composition."* MicroPython is exactly that host. The kernel was designed for it.

The only obstacle is that `step()` blocks:

```cpp
left_.requestSample();
sleeper_.sleepMillis(kSettle);   // 4 ms
left_.tick(clock_.nowMicros());

right_.requestSample();
sleeper_.sleepMillis(kSettle);   // 4 ms
right_.tick(clock_.nowMicros());
```

With `kSettle = 4`, `step()` occupies roughly 9–10 ms of the 24 ms cycle including bus time.

**Restructure `step()` into a re-entrant non-blocking state machine.** Each settle becomes "return, re-enter no sooner than 4 ms" instead of "sleep." Then drive it from a pended low-priority SWI off the system timer:

- No fiber, therefore no stack copy and no `malloc` inside a switch.
- No contact with the MicroPython heap; state lives in a plain C struct, handed to Python through a seqlock (the writer now preempts the reader).
- Cadence becomes fully independent of Python execution. The starvation hole closes.
- `dt` is already measured per cycle (`measuredPeriodUs`, `differential_drive.cpp:526`), and pacing is already absolute-deadline, so variable re-entry costs nothing in the control law. `kMaxSampleAge` (200 ms) is unaffected.
- Nezha bus transactions run a few hundred microseconds — acceptable in a pended SWI, not at timer IRQ priority.

**Cost:** this is a `vendor/` change, which means it happens in radio-robot under `src/tests/diffdrive/`. That is where it belongs; the test suite already gates the control law and the state-machine split is exactly the kind of change it exists to protect.

**Sequencing:** build M1 as planned. Score the M1 safety triple. Decide from that evidence whether the fiber is survivable in a classroom before committing to the restructure.

---

## 4. M2's gate does not test what it appears to test

**Status:** correct as a lint, mislabeled as a load-path proof.

The M2 gate includes *"mpy-cross compiles every `src/upy/*.py`."* `micropython-microbit-v2` does not define `MICROPY_PERSISTENT_CODE_LOAD` in `src/codal_port/mpconfigport.h`, so it takes the upstream default of 0. **The board cannot import a `.mpy` from the filesystem.** Verify on hardware by attempting one import; if it fails, the gate is a syntax check only, which is fine as long as it is labelled as one.

The mechanism you actually want is already wired. `src/codal_port/Makefile` sets `FROZEN_MANIFEST ?= manifest.py`, and `src/codal_port/manifest.py` currently reads:

```python
freeze("modules", "neopixel.py", opt=3)
```

Add your modules there. Frozen bytecode executes from ROM and costs almost nothing on import.

**Given `MICROBIT_HEAP_SIZE` is cut to 40 KB (`codal_overlay.json`) to buy CODAL ~24 KB, freeze everything.** Reserve the ~30 KB filesystem for `gopiv.json` and student code. Note the tradeoff `manifest.py` freezing imposes: every Python change requires a firmware rebuild and reflash, which is slower than the filesystem path during M3–M5 development. Freeze at M5 stabilisation, develop on the filesystem, and measure the heap delta at the M6 RAM/flash checkpoint.

---

## Smaller notes

- **`cyclePeriod` comment vs. reality.** `differential_drive.h:167` documents the 24 ms cadence as `>= 2*kSettle + margin`. With two bus round trips the real floor is closer to 10 ms of occupied cycle. The comms pump budget (M3's `micropython.schedule` bounded work) should be sized against ~14 ms of available window per cycle, not 24.
- **`cycleOverrunCount_`** is the metric that tells you whether any of the above is actually biting. Surface it in telemetry from M1, not M5 — it is the only direct evidence of cadence loss and you want it during the risky milestone, not after.
- **Seqlock, if the SWI path is taken.** Writer increments a sequence counter to odd, writes the struct, increments to even. Reader samples seq, copies, resamples, retries on mismatch. No locks, no priority inversion, and nothing in the writer touches the MicroPython heap.

---

## Summary

| # | Finding | Action |
|---|---|---|
| 1 | Heap corruption is CODAL's shared-stack + in-switch `malloc`, not sweep timing | Record the hook question as permanently closed |
| 2 | Starvation watchdog is safety-only; real trigger is `radio.receive()` polling | Add polling case to M1 gate; make watchdog visible in TLM + display |
| 3 | Fiber is removable — kernel sanctions it; only the settle blocks | Restructure `step()` in radio-robot if M1 safety reads badly |
| 4 | `.mpy` cannot be loaded by this port | Relabel M2 gate as lint; use `manifest.py` freezing, at M5 |
