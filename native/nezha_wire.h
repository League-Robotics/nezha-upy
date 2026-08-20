// nezha_wire.h -- the raw Nezha zero-duty write frame, factored out so
// the pre-VM boot zero-write and the VM-hook starvation watchdog's fault
// response -- both of which must write a hardware zero without going
// through a possibly-not-running DifferentialDrive -- share one
// definition.
//
// Frame layout and register (0x60 "motor run") read directly off
// vendor/nezha_motor.cpp's writeMotorRun(), copied as DATA (the wire
// byte layout), not logic: no write shaping, no slew, no dedupe, no
// throttle. Deliberate -- both call sites exist because the shaped path
// might not be running; an unshaped, unconditional zero write is the
// point (matches Motor::emergencyStop()'s contract: "zero is never
// shaped").
#pragma once

#include <cstdint>

#include "hal/i2c_bus.h"

namespace Native {

constexpr uint8_t kNezhaDeviceAddr7 = 0x10;

// Writes a single unconditional zero-speed "motor run" frame to one
// port. Returns the bus status (0 == kOk). direction is irrelevant at
// speed 0, so kDirCw (1) is used unconditionally.
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
// success (bus status 0). Matches spec Section 8's watchdog retry x2
// contract.
inline void writeNezhaZeroDutyWithRetry(Hal::I2CBus& bus, uint32_t port,
                                         int retries) {
  for (int attempt = 0; attempt <= retries; ++attempt) {
    if (writeNezhaZeroDuty(bus, port) == 0) {
      return;
    }
  }
}

}  // namespace Native
