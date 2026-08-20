#include "watchdog.h"

extern "C" {
#include "py/mphal.h"    // mp_hal_ticks_us()
#include "microbithal.h"  // microbit_hal_display_set_pixel()
}

#include "nezha_wire.h"

namespace Native {

namespace {
// Fault display: a fixed diagonal-X across the 5x5 LED matrix, visually
// distinct from digits/scrolling text. Cheap (five pixel writes, no
// allocation, no fiber involvement) -- safe from the VM hook.
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

  // Skip the output() copy unless kPollIntervalUs has elapsed.
  // Unsigned-wraparound-safe (same idiom as I2cBroker::waitForClearance()).
  if (static_cast<int32_t>(now - lastPollUs_) <
      static_cast<int32_t>(kPollIntervalUs)) {
    return;
  }
  lastPollUs_ = now;

  const DiffDrive::DifferentialDrive::Output out = kernel_.output();
  if (out.cycleCount != lastCycleCount_) {
    // Fiber is alive and advancing -- healthy.
    lastCycleCount_ = out.cycleCount;
    lastAdvanceUs_ = now;
    return;
  }

  // cycleCount hasn't moved. Only a fault if wheels are actually
  // commanded -- a parked/neutral/estopped robot idling is not a fault.
  const bool wheelsCommanded =
      out.ready && !out.leaseExpired && !out.estopped && !out.stallHalted;
  if (!wheelsCommanded) {
    return;
  }

  if (static_cast<int32_t>(now - lastAdvanceUs_) >=
      static_cast<int32_t>(kStallThresholdUs)) {
    trip();
    // Re-arm so a still-stalled kernel doesn't retrip every interval;
    // faultLatched_ is the durable signal from here on.
    lastAdvanceUs_ = now;
  }
}

void Watchdog::trip() {
  // Raw, unshaped zero -- bypasses the kernel (which might be dead).
  // Never yields.
  writeNezhaZeroDutyWithRetry(bus_, leftPort_, kZeroWriteRetries);
  writeNezhaZeroDutyWithRetry(bus_, rightPort_, kZeroWriteRetries);

  ++tripCount_;
  if (!faultLatched_) {
    faultLatched_ = true;
    showFaultIndicator();
  }
}

}  // namespace Native
