// watchdog.h -- Watchdog: the zero-only starvation watchdog (spec
// Sections 5/7.2/8). Invoked from MICROPY_VM_HOOK_POLL (mpconfigport.h,
// patched by build.sh's --with-diffdrive step) -- the existing stock
// hook point, firing roughly every 64 bytecodes.
//
// HARD SAFETY INVARIANT: poll() and everything it calls must never
// yield, sleep, or trigger a CODAL fiber switch (no schedule(), no
// fiber_sleep(), no create_fiber()) -- a fiber switch from inside VM
// bytecode dispatch corrupts the heap (CODAL's verify_stack_size() does
// malloc/free mid-switch, clobbering MicroPython's nlr_top chain / the
// GC's conservative stack scan; see docs/nezha-upy-review.md Sec 1).
// poll()'s only I/O is a synchronous, blocking I2C write via
// writeNezhaZeroDutyWithRetry() on the rare fault path -- ordinary bus
// wait, no fiber involvement.
//
// Covers both the busy-wait `while True: pass` and the polling idiom
// `while True: p = radio.receive()` identically: neither reaches
// microbit_hal_idle(), so the kernel fiber never runs and
// Output.cycleCount stops advancing -- this watchdog's only signal.
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
  // usual two-wheel wiring until diffdrive.configure() supplies the
  // robot's real wiring.
  void setPorts(uint32_t leftPort, uint32_t rightPort) {
    leftPort_ = leftPort;
    rightPort_ = rightPort;
  }

  // Called from MICROPY_VM_HOOK_POLL. Cheap on every call except the
  // rare fault path: internally throttled to at most one output() copy
  // per kPollIntervalUs.
  void poll();

  bool faultLatched() const { return faultLatched_; }
  uint32_t tripCount() const { return tripCount_; }

  // Test/bench escape hatch -- not exposed to Python; the fault stays
  // latched until reboot by design (spec Section 8).
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

  // [us] how often poll() samples output(); well under the 250 ms
  // stall threshold.
  static constexpr uint32_t kPollIntervalUs = 20000;
  // [us] stall threshold (spec Section 5/8).
  static constexpr uint32_t kStallThresholdUs = 250000;
  static constexpr int kZeroWriteRetries = 2;
};

}  // namespace Native
