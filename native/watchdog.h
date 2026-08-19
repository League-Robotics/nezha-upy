// watchdog.h -- Watchdog: the zero-only starvation watchdog required by
// docs/design/specification.md Sections 5/7.2/8 and this ticket's
// acceptance criteria.
//
// Invoked from MICROPY_VM_HOOK_POLL (mpconfigport.h, patched by
// build.sh's --with-diffdrive step) -- the ALREADY-EXISTING stock hook
// point (fires roughly every 64 bytecodes; see native/README.md for why
// this is the sanctioned integration point and not a new one).
//
// HARD SAFETY INVARIANT: poll() and everything it calls must never yield,
// sleep, or trigger a CODAL fiber switch (no schedule(), no
// fiber_sleep(), no create_fiber()). Per
// docs/nezha-upy-review.md Section 1 / spec Section 7.1, a fiber switch
// from inside VM bytecode dispatch corrupts the heap (CODAL's
// verify_stack_size() does malloc/free mid-switch, replacing the bytes
// under MicroPython's nlr_top chain / the GC's conservative stack scan).
// poll()'s only I/O is a synchronous, blocking I2C write via
// writeNezhaZeroDutyWithRetry() -- ordinary bus wait, no fiber
// involvement -- and that write only happens on the rare fault path, not
// on every call.
//
// Covers BOTH M1 safety-case shapes (busy-wait `while True: pass` and the
// realistic polling idiom `while True: p = radio.receive()`) identically:
// neither ever reaches microbit_hal_idle(), so in both cases the kernel
// fiber never gets scheduled and its Output.cycleCount stops advancing --
// this watchdog's only signal. It does not distinguish the two shapes and
// does not need to.
#pragma once

#include <cstdint>

#include "../vendor/differential_drive.h"
#include "hal/i2c_bus.h"

namespace Native {

class Watchdog {
 public:
  Watchdog(DiffDrive::DifferentialDrive& kernel, Hal::I2CBus& bus)
      : kernel_(kernel), bus_(bus) {}

  // Ports to zero if the watchdog trips. Defaults match this codebase's
  // usual two-wheel wiring (left_port=1, right_port=2, mirroring
  // reference/modrobot's kLeftPort/kRightPort) until diffdrive.configure()
  // supplies the robot's real wiring.
  void setPorts(uint32_t leftPort, uint32_t rightPort) {
    leftPort_ = leftPort;
    rightPort_ = rightPort;
  }

  // Called from MICROPY_VM_HOOK_POLL. Cheap on every call except the rare
  // fault path: internally throttled so the (comparatively expensive)
  // DifferentialDrive::output() seq-consistent copy happens at most once
  // per kPollIntervalUs, not on every one of the ~thousands of hook
  // firings per second a tight Python loop produces.
  void poll();

  bool faultLatched() const { return faultLatched_; }
  uint32_t tripCount() const { return tripCount_; }

  // Test/bench escape hatch -- NOT exposed to Python in this ticket (no
  // acceptance criterion asks for a clear function; the fault is meant to
  // stay visible until the next boot, matching the "latch" contract in
  // spec Section 8). Kept so a future ticket can wire a clear if wanted.
  void clearFault() { faultLatched_ = false; }

 private:
  void trip();

  DiffDrive::DifferentialDrive& kernel_;
  Hal::I2CBus& bus_;

  uint32_t leftPort_ = 1;
  uint32_t rightPort_ = 2;

  uint32_t lastPollUs_ = 0;
  bool primed_ = false;

  uint32_t lastCycleCount_ = 0;
  uint32_t lastAdvanceUs_ = 0;

  bool faultLatched_ = false;
  uint32_t tripCount_ = 0;

  // [us] how often poll() actually samples output() -- cheap early-exit
  // in between. 20 ms is well under the 250 ms stall threshold, so the
  // stall is still caught within one polling granularity of the deadline.
  static constexpr uint32_t kPollIntervalUs = 20000;
  // [us] stall threshold, per spec Section 5/8 ("cycles stall > 250 ms
  // with wheels commanded").
  static constexpr uint32_t kStallThresholdUs = 250000;
  static constexpr int kZeroWriteRetries = 2;
};

}  // namespace Native
