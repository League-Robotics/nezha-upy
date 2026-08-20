// device_config.h -- Hal::MotorConfig, reverse-engineered from every
// field vendor/nezha_motor.cpp actually reads (not copied from
// radio-robot's current, already-diverged src/firm/hal/device_config.h
// -- see device_types.h).
//
// wheelTravelCalib is deliberately absent: nezha_motor.cpp never reads
// one (mm conversion belongs to the application layer).
#pragma once

#include <cstdint>

namespace Hal {

struct MotorConfig {
  // +1 or -1: corrects a mirror-mounted wheel's encoder/duty sign.
  int32_t fwdSign = 0;

  // Max |duty write step| per tick; <=0 substituted with NezhaMotor's
  // kDefaultSlewRate.
  float slewRate = 0.0f;

  // 1-based port label (the Nezha frame's own port byte).
  uint32_t port = 0;

  float reversalDwell = 0.0f;    // [ms]
  float outputDeadband = 0.0f;   // [-1, 1] fraction

  // Minimum spacing between non-stop writes to this channel. <= 0
  // disables the throttle; stop writes always bypass it.
  float writeThrottle = 0.0f;    // [us]
};

}  // namespace Hal
