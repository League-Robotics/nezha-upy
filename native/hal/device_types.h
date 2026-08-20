// device_types.h -- the narrow slice of radio-robot's Hal:: value-type
// contract vendor/nezha_motor.{h,cpp} and vendor/motor_armor.h actually
// reference. Authored fresh in native/ (vendor/'s live upstream
// counterpart has already diverged from this frozen snapshot).
#pragma once

#include <cstdint>

namespace Hal {

// Coast vs brake. nezha_motor.cpp's setNeutral() takes this but never
// branches on it -- both map to the same 0x60 speed-0 write. Kept as a
// real enum: part of nezha_motor.h's fixed override signature.
enum class Neutral : uint8_t {
  Coast,
  Brake,
};

}  // namespace Hal
