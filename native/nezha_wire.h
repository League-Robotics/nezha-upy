// nezha_wire.h -- the raw Nezha zero-duty write frame, factored out once
// so the two code paths that must write a hardware zero WITHOUT going
// through a (possibly not-yet-existing or possibly-stalled)
// DifferentialDrive object -- the pre-VM boot zero-write and the VM-hook
// starvation watchdog's fault response -- share one definition instead of
// re-deriving the wire format twice.
//
// Frame layout and register (0x60 "motor run") are read directly off
// vendor/nezha_motor.cpp's writeMotorRun() -- copied as DATA (the wire
// protocol byte layout), not logic: no write shaping, no slew, no
// dedupe, no throttle. That is deliberate here -- both call sites exist
// BECAUSE the shaped path (NezhaMotor::tick(), or the whole kernel fiber)
// might not be running; an unshaped, always-unconditional zero write is
// the point, matching Motor::emergencyStop()'s own contract ("the one
// call that must not depend on a healthy tick()... Zero is never
// shaped").
#pragma once

#include <cstdint>

#include "hal/i2c_bus.h"

namespace Native {

constexpr uint8_t kNezhaDeviceAddr7 = 0x10;

// Writes a single unconditional zero-speed "motor run" frame to one port.
// Returns the bus status (0 == kOk). direction is irrelevant at speed 0,
// so kDirCw (1) is used unconditionally.
inline int writeNezhaZeroDuty(Hal::I2CBus& bus, uint32_t port) {
  uint8_t buf[8] = {
      0xFF, 0xF9,
      static_cast<uint8_t>(port),
      /*direction=*/1,
      0x60,
      /*speed=*/0,
      0xF5,
      0x00,
  };
  return bus.write(static_cast<uint16_t>(kNezhaDeviceAddr7 << 1), buf, 8,
                    /*repeated=*/false, /*preClear=*/0, /*postClear=*/4000);
}

// Retries the write up to (1 + retries) times, stopping at the first
// success (bus status 0). Matches spec Section 8's "watchdog: zero duty
// write retry x2" contract.
inline void writeNezhaZeroDutyWithRetry(Hal::I2CBus& bus, uint32_t port,
                                         int retries) {
  for (int attempt = 0; attempt <= retries; ++attempt) {
    if (writeNezhaZeroDuty(bus, port) == 0) {
      return;
    }
  }
}

}  // namespace Native
