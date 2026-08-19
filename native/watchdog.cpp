#include "watchdog.h"

extern "C" {
#include "py/mphal.h"    // mp_hal_ticks_us()
#include "microbithal.h"  // microbit_hal_display_set_pixel()
}

#include "nezha_wire.h"

namespace Native {

namespace {
// Display indication (spec Section 7.2: "a silent stop at 250 ms is
// indistinguishable from a hardware fault to a student" -- fault bit in
// telemetry alone is not enough). A fixed diagonal-X pattern across the
// 5x5 LED matrix: visually distinct from digits/scrolling text, cheap
// (five direct pixel writes, no allocation, no fiber involvement) and
// safe to call from the VM hook on the rare trip edge.
void showFaultIndicator() {
  static const int kXs[5] = {0, 1, 2, 3, 4};
  static const int kYsA[5] = {0, 1, 2, 3, 4};
  static const int kYsB[5] = {4, 3, 2, 1, 0};
  for (int i = 0; i < 5; ++i) {
    microbit_hal_display_set_pixel(kXs[i], kYsA[i], 255);
    microbit_hal_display_set_pixel(kXs[i], kYsB[i], 255);
  }
}
}  // namespace

void Watchdog::poll() {
  const uint32_t now = mp_hal_ticks_us();

  if (!primed_) {
    primed_ = true;
    lastPollUs_ = now;
    lastAdvanceUs_ = now;
    lastCycleCount_ = kernel_.output().cycleCount;
    return;
  }

  // Cheap throttle: skip the output() copy unless kPollIntervalUs has
  // elapsed since the last sample. Unsigned wraparound-safe (see
  // I2cBroker::waitForClearance() for the same idiom).
  if (static_cast<int32_t>(now - lastPollUs_) <
      static_cast<int32_t>(kPollIntervalUs)) {
    return;
  }
  lastPollUs_ = now;

  const DiffDrive::DifferentialDrive::Output out = kernel_.output();
  if (out.cycleCount != lastCycleCount_) {
    // Kernel fiber is alive and advancing -- healthy. Refresh the
    // advance timestamp and remember the fresh cycle count.
    lastCycleCount_ = out.cycleCount;
    lastAdvanceUs_ = now;
    return;
  }

  // cycleCount has not moved since the last sample. Only a genuine
  // starvation concern if wheels are actually commanded right now, per
  // the kernel's OWN last-known state -- a parked/neutral/estopped robot
  // whose fiber has gone idle between commands is not a fault.
  const bool wheelsCommanded =
      out.ready && !out.leaseExpired && !out.estopped && !out.stallHalted;
  if (!wheelsCommanded) {
    return;
  }

  if (static_cast<int32_t>(now - lastAdvanceUs_) >=
      static_cast<int32_t>(kStallThresholdUs)) {
    trip();
    // Re-arm the advance clock so a still-stalled kernel does not retrip
    // (and re-hammer the bus) on every subsequent poll interval; a
    // genuinely still-stalled kernel simply never advances cycleCount
    // again, so wheelsCommanded's own snapshot goes stale too -- the
    // latch (faultLatched_) is the durable signal from here on, not
    // repeated tripping.
    lastAdvanceUs_ = now;
  }
}

void Watchdog::trip() {
  // Raw, unconditional, unshaped zero -- bypasses the kernel entirely
  // (the kernel fiber is exactly what might be dead right now). Never
  // yields; see this file's own header for why that is safe here.
  writeNezhaZeroDutyWithRetry(bus_, leftPort_, kZeroWriteRetries);
  writeNezhaZeroDutyWithRetry(bus_, rightPort_, kZeroWriteRetries);

  ++tripCount_;
  if (!faultLatched_) {
    faultLatched_ = true;
    showFaultIndicator();
  }
}

}  // namespace Native
