// device_config.h -- Hal::MotorConfig, reverse-engineered from every field
// vendor/nezha_motor.cpp actually reads (config_.fwdSign, config_.slewRate,
// config_.port, config_.reversalDwell, config_.outputDeadband,
// config_.writeThrottle). See device_types.h's file header for why this is
// authored fresh in native/ rather than copied from radio-robot's current
// src/firm/hal/device_config.h (which has already diverged from the
// vendored snapshot -- e.g. it has no writeThrottle field at all).
//
// wheelTravelCalib is deliberately NOT here: nezha_motor.h's own comment
// says applyTravelCalib() "is GONE -- counts-native leaf ... the mm
// conversion belongs to the application layer," and nezha_motor.cpp never
// reads a travel-calib field, so this leaf-facing config has none.
#pragma once

#include <cstdint>

namespace Hal {

struct MotorConfig {
  // +1 or -1: corrects a mirror-mounted wheel's encoder/duty sign.
  int32_t fwdSign = 0;

  // Maximum |duty write step| per tick, in the leaf's raw hardware write
  // domain (integer PWM-percent register). <= 0 substituted with
  // NezhaMotor's own kDefaultSlewRate at reconfigure() time.
  float slewRate = 0.0f;

  // 1-based port label (the Nezha frame's own port byte).
  uint32_t port = 0;

  float reversalDwell = 0.0f;    // [ms]
  float outputDeadband = 0.0f;   // [-1, 1] fraction

  // Minimum spacing between non-stop writes to this channel. <= 0 disables
  // the throttle (write-on-change + slew still bound the write rate). Stop
  // writes always bypass it -- see nezha_motor.cpp's writeRawDuty().
  float writeThrottle = 0.0f;    // [us]
};

}  // namespace Hal
