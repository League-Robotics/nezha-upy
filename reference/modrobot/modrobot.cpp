/*
 * modrobot.cpp -- MicroPython C++ module: robot
 *
 * Wraps real firmware hardware drivers (NezhaMotor, RealOtos,
 * LineSensorLeaf, ColorSensorLeaf) so Python can drive the robot
 * and read sensors from the REPL.
 *
 * API:
 *   import robot
 *
 *   # Higher-level exploratory motion surface, shaped closer to the real
 *   # firmware interface.
 *   robot.move(v_x_mm_s, omega_rad_s, distance_mm, timeout_ms)
 *   robot.turn(omega_rad_s, angle_rad, timeout_ms)
 *   robot.go_to(x_mm, y_mm, frame, speed_mm_s, arrive_mm, timeout_ms)
 *
 *   # Low-level bench helpers retained for direct wheel-duty experiments.
 *   robot.drive(left_pct, right_pct)          # run for kDefaultMoveMs then stop
 *   robot.move_wheels(left_pct, right_pct, ms)
 *   robot.set_wheels(left_pct, right_pct)     # continuous duty command (no auto-stop)
 *   robot.stop()
 *   robot.encoders()
 *
 *   # Sensors / servo.
 *   robot.otos()
 *   robot.line()
 *   robot.color()
 *   robot.servo(port, angle_deg)
 */

extern "C" {
#include "py/runtime.h"
#include "py/mphal.h"
#include "py/objstr.h"
#include "microbithal.h"
}

#include "hardware/nezha/nezha_motor.h"
#include "hardware/generic/real_otos.h"
#include "hardware/planetx/line_sensor.h"
#include "hardware/planetx/color_sensor.h"
#include "hal/i2c_bus.h"
#include "hal/motor.h"
#include "hal/device_config.h"
#include "messages/commands.h"
#include "messages/common.h"
#include "messages/envelope.h"
#include "messages/telemetry.h"
#include "messages/wire.h"
#include "messages/wire_runtime.h"
#include "wifi_stdio.h"

#include <cmath>
#include <cstdio>
#include <cstring>

// microbit_friendly_name()/microbit_serial_number() -- CODAL device identity,
// declared inside `namespace codal` by MicroBitDevice.h (C++ linkage, NOT
// extern "C"). modrobot.cpp builds under codal_port, off MicroBitDevice.h's
// normal codal_app include path (the way codal_app/microbithal.cpp reaches it
// via `#include "MicroBit.h"`), so forward-declare instead of including,
// matching that header's linkage exactly rather than guessing extern "C".
namespace codal {
uint32_t microbit_serial_number();
char* microbit_friendly_name();
}  // namespace codal

namespace {

class HalI2CBus final : public Hal::I2CBus {
 public:
  int write(uint16_t address, uint8_t* data, int len, bool repeated = false,
            uint32_t preClear = 0, uint32_t postClear = 0) override {
    const uint8_t addr7 = static_cast<uint8_t>(address >> 1);
    waitForClearance(addr7, preClear);
    const int result = microbit_hal_i2c_writeto(addr7, data, len, !repeated);
    recordEnd(addr7, postClear);
    return result;
  }

  int read(uint16_t address, uint8_t* data, int len, bool repeated = false,
           uint32_t preClear = 0, uint32_t postClear = 0) override {
    const uint8_t addr7 = static_cast<uint8_t>(address >> 1);
    waitForClearance(addr7, preClear);
    const int result = microbit_hal_i2c_readfrom(addr7, data, len, !repeated);
    recordEnd(addr7, postClear);
    return result;
  }

  uint32_t clearanceSafetyNetCount() const override {
    return clearanceSafetyNetCount_;
  }

 private:
  struct DeviceState {
    uint64_t lastEnd = 0;   // [us]
    uint64_t readyAt = 0;   // [us]
  };

  void waitForClearance(uint8_t addr7, uint32_t preClear) {
    const uint64_t preDeadline =
        devices_[addr7].lastEnd + static_cast<uint64_t>(preClear);
    uint64_t entryDeadline = devices_[addr7].readyAt;
    if (preDeadline > entryDeadline) {
      entryDeadline = preDeadline;
    }
    uint64_t now = static_cast<uint64_t>(mp_hal_ticks_us());
    if (now >= entryDeadline) {
      return;
    }
    ++clearanceSafetyNetCount_;
    const uint32_t shortfallMs =
        static_cast<uint32_t>((entryDeadline - now + 999ULL) / 1000ULL);
    if (shortfallMs > 0) {
      mp_hal_delay_ms(shortfallMs);
    }
  }

  void recordEnd(uint8_t addr7, uint32_t postClear) {
    const uint64_t now = static_cast<uint64_t>(mp_hal_ticks_us());
    devices_[addr7].lastEnd = now;
    devices_[addr7].readyAt = now + static_cast<uint64_t>(postClear);
  }

  DeviceState devices_[128] = {};
  uint32_t clearanceSafetyNetCount_ = 0;
};

constexpr float kDefaultSlewRate = 25.0f;
constexpr float kDefaultDeadband = 0.03f;
constexpr float kDefaultReversalDwell = 100.0f;
constexpr float kLeftTravelCalib = 0.7165f;
constexpr float kRightTravelCalib = 0.7077f;
constexpr uint32_t kLeftPort = 1;
constexpr uint32_t kRightPort = 2;
constexpr int32_t kLeftFwdSign = 1;
constexpr int32_t kRightFwdSign = -1;
constexpr uint32_t kDefaultMoveMs = 600;
// A single exploratory WHEELS frame must never be able to buy unbounded
// unsupervised motion: a units bug (seconds treated as milliseconds) turned
// a 500 ms hold into mp_hal_delay_ms(500000) and ran gopiv's wheels for 8+
// minutes unsupervised (2026-08-14 night incident; see handleWheels()'s own
// comment). Every WHEELS hold window is hard-clamped to this ceiling
// regardless of what the wire frame asked for.
constexpr uint32_t kMaxWheelsWindowMs = 5000;
constexpr uint32_t kYieldIntervalMs = 10;
constexpr float kTrackWidthMm = 128.0f;
constexpr float kDutyPerSpeed = 0.001182f;  // [duty/(mm/s)]
constexpr float kDefaultGotoSpeed = 80.0f;  // [mm/s]
constexpr float kDefaultTurnOmega = 1.2f;
constexpr float kDefaultArriveMm = 15.0f;
constexpr float kGotoHeadingK = 2.5f;
constexpr float kGotoMaxOmega = 1.8f;       // [rad/s]
constexpr float kGotoTurnInPlace = 1.0f;    // [rad]
constexpr float kGotoMinSpeed = 25.0f;      // [mm/s]
constexpr float kPi = 3.14159265358979323846f;
constexpr uint32_t kWifiTlmPeriodMs = 50;
constexpr uint32_t kWifiCyclePeriodUs = 32000;
constexpr size_t kV5LineBuffer = 224;
constexpr size_t kV5RawMax = msg::wire::kReplyEnvelopeMaxEncodedSize;
constexpr size_t kV5CombinedMax = kV5RawMax + 2;
constexpr size_t kV5FrameMax =
    kV5CombinedMax + (kV5CombinedMax / WireRuntime::kCobsMaxBlockLength) + 1;
constexpr uint8_t kV5CobsDelimiter = 0x0A;
constexpr uint32_t kFlagActive = 1u << 2;
constexpr uint32_t kFlagConnLeft = 1u << 3;
constexpr uint32_t kFlagConnRight = 1u << 4;
constexpr uint32_t kFlagLineFresh = 1u << 5;
constexpr uint32_t kFlagOtosPresent = 1u << 0;
constexpr uint32_t kFlagOtosConnected = 1u << 1;
constexpr uint32_t kFlagLinePresent = 1u << 13;
constexpr uint32_t kFlagColorPresent = 1u << 14;
constexpr uint32_t kFlagColorFresh = 1u << 23;
constexpr uint32_t kFlagReady = 1u << 26;

float clampf(float v, float lo, float hi) {
  return v < lo ? lo : (v > hi ? hi : v);
}

float wrapRad(float a) {
  while (a > kPi) {
    a -= 2.0f * kPi;
  }
  while (a < -kPi) {
    a += 2.0f * kPi;
  }
  return a;
}

Hal::MotorConfig makeMotorConfig(uint32_t port, int32_t fwdSign, float calib) {
  Hal::MotorConfig c;
  c.port = port;
  c.fwdSign = fwdSign;
  c.wheelTravelCalib = calib;
  c.slewRate = kDefaultSlewRate;
  c.reversalDwell = kDefaultReversalDwell;
  c.outputDeadband = kDefaultDeadband;
  c.polled = true;
  return c;
}

class Drivetrain final {
 public:
  Drivetrain()
      : leftCfg_(makeMotorConfig(kLeftPort, kLeftFwdSign, kLeftTravelCalib)),
        rightCfg_(makeMotorConfig(kRightPort, kRightFwdSign, kRightTravelCalib)),
        leftMotor_(bus_, leftCfg_),
        rightMotor_(bus_, rightCfg_) {}

  void ensureStarted() {
    if (started_) {
      return;
    }
    leftMotor_.begin();
    rightMotor_.begin();
    // Boot-time zero write (2026-08-14 vevov/gopiv runaway; sprint 133's
    // NezhaMotor firstWrite sentinel). The Nezha brick LATCHES its last
    // commanded speed in its own onboard firmware and does NOT reset when
    // the nRF52 resets -- so a previous life's nonzero command survives
    // into this boot until something writes an actual zero over it.
    // setNeutral() (mode_ = Neutral) plus the tickBoth() below IS that
    // write: NezhaMotor::tick()'s Neutral branch calls
    // writeShapedDuty(0.0f, ...), whose duty==0.0f case bypasses
    // slew/dwell shaping and the write-on-change dedup entirely, and
    // because lastWrittenPct_ starts at the -128 sentinel ("never
    // written"), this very first tick is provably a genuine I2C zero
    // write, not a suppressed no-op (see nezha_motor.cpp's writeRawDuty()).
    // This must happen before anything else -- setDuty() included -- can
    // stage a nonzero duty.
    leftMotor_.setNeutral(Hal::Neutral::Coast);
    rightMotor_.setNeutral(Hal::Neutral::Coast);
    started_ = true;
    tickBoth();
  }

  void driveWheelPct(int leftPct, int rightPct, uint32_t durationMs) {
    const bool interrupted = runDutyWindow(
        static_cast<float>(leftPct) / 100.0f,
        static_cast<float>(rightPct) / 100.0f, durationMs);
    if (interrupted) {
      // Only safe to raise here: driveWheelPct() is called exclusively
      // from robot.move_wheels()/robot.drive()'s own Python call frame
      // (robot_move_wheels_fn), which always owns a live nlr context. See
      // runDutyWindow()'s own comment for why it cannot do this raise
      // itself.
      mp_raise_type(&mp_type_KeyboardInterrupt);
    }
  }

  // Stages leftDuty/rightDuty (already-clamped, -1..1) and holds them for
  // durationMs [ms], ticking both motors every pass so the staged duty
  // actually reaches the I2C bus -- a bare mp_hal_delay_ms() never ticks the
  // polled motors, so the wheels never spin. Polls ctrl-c each pass exactly
  // like the loop this was extracted from. Returns true if ctrl-c fired
  // (motors are already stopped either way).
  //
  // Ctrl-c handling: this is shared by driveWheelPct() (percent-duty bench
  // helper, called only from robot.move_wheels()'s own Python call frame --
  // a live nlr context, safe to raise into) and handleWheels() (the v5
  // WHEELS command, reachable from BOTH robot.enter_v5()'s Python call
  // frame AND robot_v5_service(), the always-on background engine invoked
  // from the VM hook on every N bytecodes -- see robot_v5_service()'s own
  // comment). Raising a KeyboardInterrupt straight out of here would be
  // safe on the first path and is NOT safe on the second (no Python call
  // frame necessarily owns that context), and this function has no way to
  // tell which caller it is running under. The simplest rule that is safe
  // for both: this function NEVER raises. On ctrl-c it stops the motors
  // (the part that actually matters for safety) and returns true so the
  // caller can decide, in ITS OWN known-safe-or-not context, whether to
  // re-raise -- driveWheelPct() does; handleWheels() deliberately does not
  // (see its own comment).
  bool runDutyWindow(float leftDuty, float rightDuty, uint32_t durationMs) {
    ensureStarted();
    leftMotor_.setDuty(leftDuty);
    rightMotor_.setDuty(rightDuty);

    const uint64_t startUs = static_cast<uint64_t>(mp_hal_ticks_us());
    const uint64_t endUs = startUs + static_cast<uint64_t>(durationMs) * 1000ULL;
    uint64_t lastYieldUs = startUs;

    while (static_cast<uint64_t>(mp_hal_ticks_us()) < endUs) {
      if (microbit_hal_poll_ctrl_c()) {
        stopMotors();
        return true;
      }
      tickBoth();
      const uint64_t nowUs = static_cast<uint64_t>(mp_hal_ticks_us());
      if (nowUs - lastYieldUs >= static_cast<uint64_t>(kYieldIntervalMs) * 1000ULL) {
        mp_hal_delay_ms(1);
        lastYieldUs = static_cast<uint64_t>(mp_hal_ticks_us());
      }
    }
    stopMotors();
    return false;
  }

  void setDutyCommand(float leftDuty, float rightDuty) {
    ensureStarted();
    leftMotor_.setDuty(clampf(leftDuty, -1.0f, 1.0f));
    rightMotor_.setDuty(clampf(rightDuty, -1.0f, 1.0f));
    tickBoth();
  }

  void tick() {
    ensureStarted();
    tickBoth();
  }

  void stopMotors() {
    ensureStarted();
    leftMotor_.setNeutral(Hal::Neutral::Coast);
    rightMotor_.setNeutral(Hal::Neutral::Coast);
    tickBoth();
  }

  void encoders(int32_t& left, int32_t& right) {
    ensureStarted();
    tickBoth();
    left = leftCounts_;
    right = rightCounts_;
  }

  void wheelPositions(float& leftMm, float& rightMm) {
    ensureStarted();
    tickBoth();
    leftMm = leftMotor_.position();
    rightMm = rightMotor_.position();
  }

 private:
  void tickBoth() {
    const uint64_t nowUs = static_cast<uint64_t>(mp_hal_ticks_us());
    leftMotor_.requestSample();
    leftMotor_.tick(nowUs);
    rightMotor_.requestSample();
    rightMotor_.tick(nowUs + 4000);
    leftCounts_ = static_cast<int32_t>(
        lroundf((leftMotor_.position() / kLeftTravelCalib) * 10.0f));
    rightCounts_ = static_cast<int32_t>(
        lroundf((rightMotor_.position() / kRightTravelCalib) * 10.0f));
  }

  HalI2CBus bus_;
  Hal::MotorConfig leftCfg_, rightCfg_;
  Hardware::NezhaMotor leftMotor_, rightMotor_;
  bool started_ = false;
  int32_t leftCounts_ = 0;
  int32_t rightCounts_ = 0;
};

Drivetrain& dt() {
  static Drivetrain inst;
  return inst;
}

Hal::OtosConfig defaultOtosConfig() {
  Hal::OtosConfig c{};
  return c;
}

class OtosSensor final {
 public:
  OtosSensor() : otos_(bus_, defaultOtosConfig()) {}

  void ensureStarted() {
    if (started_) {
      return;
    }
    otos_.begin();
    started_ = true;
  }

  void read(float& x, float& y, float& h) {
    ensureStarted();
    const uint64_t nowUs = static_cast<uint64_t>(mp_hal_ticks_us());
    if (otos_.readDue(nowUs)) {
      otos_.tick(nowUs);
    }
    const auto pose = otos_.pose();
    x = pose.x;
    y = pose.y;
    h = pose.heading;
  }

 private:
  HalI2CBus bus_;
  Hardware::RealOtos otos_;
  bool started_ = false;
};

OtosSensor& otos() {
  static OtosSensor inst;
  return inst;
}

Hal::LineConfig defaultLineConfig() {
  Hal::LineConfig c{};
  return c;
}

class LineSensor final {
 public:
  LineSensor() : leaf_(bus_, defaultLineConfig()) {}

  void ensureStarted() {
    if (started_) {
      return;
    }
    for (int i = 0; i < 25 && !leaf_.detectDone(); ++i) {
      const uint64_t nowUs = static_cast<uint64_t>(mp_hal_ticks_us());
      leaf_.beginStep(nowUs);
      if (!leaf_.detectDone()) {
        mp_hal_delay_ms(50);
      }
    }
    started_ = true;
  }

  void read(uint32_t out[4]) {
    ensureStarted();
    const uint64_t nowUs = static_cast<uint64_t>(mp_hal_ticks_us());
    leaf_.tick(nowUs);
    const auto& rd = leaf_.reading();
    for (int i = 0; i < 4; ++i) {
      out[i] = rd.raw[i];
    }
  }

 private:
  HalI2CBus bus_;
  Hardware::LineSensorLeaf leaf_;
  bool started_ = false;
};

LineSensor& line() {
  static LineSensor inst;
  return inst;
}

Hal::ColorConfig defaultColorConfig() {
  Hal::ColorConfig c{};
  return c;
}

class ColorSensor final {
 public:
  ColorSensor() : leaf_(bus_, defaultColorConfig()) {}

  void ensureStarted() {
    if (started_) {
      return;
    }
    for (int i = 0; i < 25 && !leaf_.detectDone(); ++i) {
      const uint64_t nowUs = static_cast<uint64_t>(mp_hal_ticks_us());
      leaf_.beginStep(nowUs);
      if (!leaf_.detectDone()) {
        mp_hal_delay_ms(50);
      }
    }
    started_ = true;
  }

  void read(uint32_t& rv, uint32_t& gv, uint32_t& bv, uint32_t& cv) {
    ensureStarted();
    const uint64_t nowUs = static_cast<uint64_t>(mp_hal_ticks_us());
    leaf_.tick(nowUs);
    const auto& rd = leaf_.reading();
    rv = rd.r;
    gv = rd.g;
    bv = rd.b;
    cv = rd.c;
  }

 private:
  HalI2CBus bus_;
  Hardware::ColorSensorLeaf leaf_;
  bool started_ = false;
};

ColorSensor& color() {
  static ColorSensor inst;
  return inst;
}

// Nezha V2 PWM jack pins: J1=S1->P1, J2=S2->P2, J3=S3->P13, J4=S4->P15
// (Digital jack pins are different: J1->P8, J2->P12, J3->P14, J4->P16.)
static int servoPin(int port) {
  switch (port) {
    case 1:
      return MICROBIT_HAL_PIN_P1;
    case 2:
      return MICROBIT_HAL_PIN_P2;
    case 3:
      return MICROBIT_HAL_PIN_P13;
    case 4:
      return MICROBIT_HAL_PIN_P15;
    default:
      return -1;
  }
}

mp_obj_t makeEncoderTuple() {
  int32_t l = 0;
  int32_t r = 0;
  dt().encoders(l, r);
  mp_obj_t items[2] = {mp_obj_new_int(l), mp_obj_new_int(r)};
  return mp_obj_new_tuple(2, items);
}

mp_obj_t makePoseTuple() {
  float x = 0.0f;
  float y = 0.0f;
  float h = 0.0f;
  otos().read(x, y, h);
  mp_obj_t items[3] = {
      mp_obj_new_float(x),
      mp_obj_new_float(y),
      mp_obj_new_float(h),
  };
  return mp_obj_new_tuple(3, items);
}

void twistToDuty(float vX, float omega, float& dutyLeft, float& dutyRight) {
  const float vLeft = vX - omega * (kTrackWidthMm * 0.5f);
  const float vRight = vX + omega * (kTrackWidthMm * 0.5f);
  dutyLeft = vLeft * kDutyPerSpeed;
  dutyRight = vRight * kDutyPerSpeed;
  const float maxAbs = fmaxf(fabsf(dutyLeft), fabsf(dutyRight));
  if (maxAbs > 1.0f) {
    dutyLeft /= maxAbs;
    dutyRight /= maxAbs;
  }
  dutyLeft = clampf(dutyLeft, -1.0f, 1.0f);
  dutyRight = clampf(dutyRight, -1.0f, 1.0f);
}

// Polls ctrl-c and, on a hit, always stops the motors first. Whether it
// THEN raises KeyboardInterrupt depends on allowRaise: true is only safe
// when the caller is running inside a Python call frame that can catch it
// (robot.move()/robot.turn()/robot.go_to()'s own call, or the TCP v5
// REPL's serviceWifiV5() loop -- both reachable only via a direct Python
// call into this module). false is what a caller uses when it MIGHT be
// running from robot_v5_service()'s background dispatch (invoked from
// microbit_hal_background_processing() on the VM hook) -- see
// runMoveDistance()'s own comment for the full reasoning, which mirrors
// Drivetrain::runDutyWindow()'s split for the WHEELS command (2026-08-14
// gopiv incident). Returns true if ctrl-c fired, so a !allowRaise caller
// can still unwind its own loop.
bool maybeCtrlC(bool allowRaise) {
  if (microbit_hal_poll_ctrl_c()) {
    dt().stopMotors();
    if (allowRaise) {
      mp_raise_type(&mp_type_KeyboardInterrupt);
    }
    return true;
  }
  return false;
}

void waitSlice(uint32_t* lastYieldUs) {
  const uint32_t nowUs = mp_hal_ticks_us();
  if (nowUs - *lastYieldUs >= kYieldIntervalMs * 1000U) {
    mp_hal_delay_ms(1);
    *lastYieldUs = mp_hal_ticks_us();
  }
}

int parseFrame(mp_obj_t frameObj) {
  if (mp_obj_is_int(frameObj)) {
    const int frame = mp_obj_get_int(frameObj);
    if (frame == 0 || frame == 1) {
      return frame;
    }
  } else {
    const char* s = mp_obj_str_get_str(frameObj);
    if (std::strcmp(s, "world") == 0 || std::strcmp(s, "WORLD") == 0) {
      return 0;
    }
    if (std::strcmp(s, "robot") == 0 || std::strcmp(s, "ROBOT") == 0) {
      return 1;
    }
  }
  mp_raise_ValueError(MP_ERROR_TEXT("frame must be 0/1 or world/robot"));
  return 0;
}

// Ctrl-c/error handling (2026-08-14 gopiv incident follow-up): this and
// runTurnAngle()/runGoTo() are reachable both from a Python call frame
// (robot.move()/robot.turn()/robot.go_to() -- always safe to raise) and,
// via handleMove()/handleGoTo(), from robot_v5_service()'s background
// dispatch (invoked from the VM hook -- NOT necessarily safe to raise; see
// handleMove()'s own comment). allowRaise carries that distinction down
// from the caller, since this function has no way to detect it on its
// own. When allowRaise is true, every failure path raises exactly as
// before (bad args, internal timeout, ctrl-c) and this function's `false`
// return is unreachable. When allowRaise is false, none of those paths
// raise -- motors are stopped and the function returns false instead, so
// a caller such as runGoTo() can tell the attempt was cut short and stop
// chaining further phases. Returns true only once the stop condition
// (distance) is actually reached.
bool runMoveDistance(float vX, float omega, float distanceMm,
                     uint32_t timeoutMs, bool allowRaise) {
  if (distanceMm <= 0.0f) {
    if (allowRaise) {
      mp_raise_ValueError(MP_ERROR_TEXT("distance must be > 0"));
    }
    return false;
  }
  if (timeoutMs == 0) {
    if (allowRaise) {
      mp_raise_ValueError(MP_ERROR_TEXT("timeout must be > 0 ms"));
    }
    return false;
  }

  float dutyLeft = 0.0f;
  float dutyRight = 0.0f;
  twistToDuty(vX, omega, dutyLeft, dutyRight);

  float leftPrev = 0.0f;
  float rightPrev = 0.0f;
  dt().wheelPositions(leftPrev, rightPrev);

  float traveled = 0.0f;
  const uint32_t startMs = mp_hal_ticks_ms();
  uint32_t lastYieldUs = mp_hal_ticks_us();

  dt().setDutyCommand(dutyLeft, dutyRight);
  while (traveled < distanceMm) {
    if (maybeCtrlC(allowRaise)) {
      return false;
    }
    if (mp_hal_ticks_ms() - startMs >= timeoutMs) {
      dt().stopMotors();
      if (allowRaise) {
        mp_raise_msg(&mp_type_RuntimeError, MP_ERROR_TEXT("move timeout"));
      }
      return false;
    }
    float leftNow = 0.0f;
    float rightNow = 0.0f;
    dt().wheelPositions(leftNow, rightNow);
    const float dCenter = ((leftNow - leftPrev) + (rightNow - rightPrev)) * 0.5f;
    traveled += fabsf(dCenter);
    leftPrev = leftNow;
    rightPrev = rightNow;
    waitSlice(&lastYieldUs);
  }
  dt().stopMotors();
  return true;
}

// See runMoveDistance()'s own comment -- same allowRaise contract, same
// reason for it. Returns true only once the stop condition (angle) is
// actually reached.
bool runTurnAngle(float omega, float angleRad, uint32_t timeoutMs,
                  bool allowRaise) {
  if (angleRad <= 0.0f) {
    if (allowRaise) {
      mp_raise_ValueError(MP_ERROR_TEXT("angle must be > 0 rad"));
    }
    return false;
  }
  if (timeoutMs == 0) {
    if (allowRaise) {
      mp_raise_ValueError(MP_ERROR_TEXT("timeout must be > 0 ms"));
    }
    return false;
  }

  float dutyLeft = 0.0f;
  float dutyRight = 0.0f;
  twistToDuty(0.0f, omega, dutyLeft, dutyRight);

  float leftPrev = 0.0f;
  float rightPrev = 0.0f;
  dt().wheelPositions(leftPrev, rightPrev);

  float turned = 0.0f;
  const uint32_t startMs = mp_hal_ticks_ms();
  uint32_t lastYieldUs = mp_hal_ticks_us();

  dt().setDutyCommand(dutyLeft, dutyRight);
  while (turned < angleRad) {
    if (maybeCtrlC(allowRaise)) {
      return false;
    }
    if (mp_hal_ticks_ms() - startMs >= timeoutMs) {
      dt().stopMotors();
      if (allowRaise) {
        mp_raise_msg(&mp_type_RuntimeError, MP_ERROR_TEXT("turn timeout"));
      }
      return false;
    }
    float leftNow = 0.0f;
    float rightNow = 0.0f;
    dt().wheelPositions(leftNow, rightNow);
    const float dTheta = ((rightNow - rightPrev) - (leftNow - leftPrev)) / kTrackWidthMm;
    turned += fabsf(dTheta);
    leftPrev = leftNow;
    rightPrev = rightNow;
    waitSlice(&lastYieldUs);
  }
  dt().stopMotors();
  return true;
}

// See runMoveDistance()'s own comment for the allowRaise contract; runGoTo
// just forwards it unchanged to the runTurnAngle()/runMoveDistance() legs
// it drives, and applies it to its own single ValueError. Returns true
// only once the target is actually reached (including the "already within
// arriveMm" immediate-arrival case); false on every early exit, raising
// or not depending on allowRaise, exactly like its two legs.
bool runGoTo(float xTarget, float yTarget, int frame, float speedMmS,
             float arriveMm, uint32_t timeoutMs, bool allowRaise) {
  if (timeoutMs == 0) {
    if (allowRaise) {
      mp_raise_ValueError(MP_ERROR_TEXT("timeout must be > 0 ms"));
    }
    return false;
  }
  if (speedMmS <= 0.0f) {
    speedMmS = kDefaultGotoSpeed;
  }
  if (arriveMm <= 0.0f) {
    arriveMm = kDefaultArriveMm;
  }

  float x0 = 0.0f;
  float y0 = 0.0f;
  float h0 = 0.0f;
  otos().read(x0, y0, h0);
  if (frame == 1) {
    const float c = cosf(h0);
    const float s = sinf(h0);
    const float wx = x0 + c * xTarget - s * yTarget;
    const float wy = y0 + s * xTarget + c * yTarget;
    xTarget = wx;
    yTarget = wy;
  }

  float x = 0.0f;
  float y = 0.0f;
  float h = 0.0f;
  otos().read(x, y, h);
  const float dx = xTarget - x;
  const float dy = yTarget - y;
  const float dist = sqrtf(dx * dx + dy * dy);
  if (dist <= arriveMm) {
    dt().stopMotors();
    return true;
  }

  const uint32_t startMs = mp_hal_ticks_ms();
  const float desiredHeading = atan2f(dy, dx);
  const float headingErr = wrapRad(desiredHeading - h);
  if (fabsf(headingErr) > 0.05f) {
    const float turnOmega =
        headingErr >= 0.0f ? kGotoMaxOmega : -kGotoMaxOmega;
    if (!runTurnAngle(turnOmega, fabsf(headingErr), timeoutMs, allowRaise)) {
      // Cut short (ctrl-c, internal timeout, bad args) and not allowed to
      // raise -- runTurnAngle() already stopped the motors; stop chaining
      // into the translate leg rather than continuing on stale heading.
      return false;
    }
  }

  const uint32_t elapsedMs = mp_hal_ticks_ms() - startMs;
  if (elapsedMs >= timeoutMs) {
    dt().stopMotors();
    return false;
  }

  const float segmentDistance = fmaxf(0.0f, dist - arriveMm);
  const uint32_t remainingMs = timeoutMs - elapsedMs;
  bool reachedTarget = true;
  if (segmentDistance > 0.0f && remainingMs > 0) {
    reachedTarget = runMoveDistance(speedMmS, 0.0f, segmentDistance,
                                    remainingMs, allowRaise);
  }

  dt().stopMotors();
  return reachedTarget;
}

uint16_t crcOverScope(const uint8_t* command, size_t commandLen,
                      const uint8_t* payload, size_t payloadLen) {
  uint16_t crc = WireRuntime::crcInit();
  if (commandLen > 0) {
    crc = WireRuntime::crcUpdate(crc, command, commandLen);
    static constexpr uint8_t kSeparator = ':';
    crc = WireRuntime::crcUpdate(crc, &kSeparator, 1);
  }
  return WireRuntime::crcUpdate(crc, payload, payloadLen);
}

const msg::VerbEntry* findVerb(const char* name, size_t len) {
  for (uint8_t i = 0; i < msg::kVerbCount; ++i) {
    const msg::VerbEntry& entry = msg::kVerbTable[i];
    const size_t entryLen = std::strlen(entry.name);
    if (entryLen == len && std::memcmp(entry.name, name, len) == 0) {
      return &entry;
    }
  }
  return nullptr;
}

uint32_t packLine(const uint32_t* reading) {
  return (reading[0] & 0xFFu) | ((reading[1] & 0xFFu) << 8) |
         ((reading[2] & 0xFFu) << 16) | ((reading[3] & 0xFFu) << 24);
}

uint8_t scaleColorChannel(uint32_t value, uint32_t fullScale) {
  if (fullScale == 0) return 0;
  const uint32_t scaled = (value * 255u) / fullScale;
  return static_cast<uint8_t>(scaled > 255u ? 255u : scaled);
}

uint32_t packColor(uint32_t r, uint32_t g, uint32_t b, uint32_t c) {
  static constexpr uint32_t kColorFullScale = 4100;
  return static_cast<uint32_t>(scaleColorChannel(r, kColorFullScale)) |
         (static_cast<uint32_t>(scaleColorChannel(g, kColorFullScale)) << 8) |
         (static_cast<uint32_t>(scaleColorChannel(b, kColorFullScale)) << 16) |
         (static_cast<uint32_t>(scaleColorChannel(c, kColorFullScale)) << 24);
}

// -- v5 reply emission: TCP (writeToSocket, coalesced) vs. UDP
// (sendV5Datagram, one datagram per call) -------------------------------
//
// Every v5 reply -- cleartext line or binary frame -- goes out through one
// of these two, chosen by `viaUdp`. This is the ONLY place that decides
// which socket a reply travels over; dispatchV5Line() and everything it
// calls (sendAck/sendError/sendTelemetry) just say which plane they are
// answering on and never touch RobotWifi directly.

bool emitWifiLine(bool viaUdp, const char* line) {
  const size_t len = std::strlen(line);
  if (viaUdp) {
    return RobotWifi::sendV5Datagram(reinterpret_cast<const uint8_t*>(line),
                                     len);
  }
  return RobotWifi::writeToSocket(reinterpret_cast<const uint8_t*>(line), len);
}

bool emitWifiFrame(bool viaUdp, const char* verb,
                   const msg::ReplyEnvelope& reply) {
  uint8_t raw[kV5RawMax];
  const uint16_t rawLen =
      msg::wire::encode(reply, raw, static_cast<uint16_t>(sizeof(raw)));
  if (rawLen == 0) return false;

  uint8_t combined[kV5CombinedMax];
  std::memcpy(combined, raw, rawLen);
  size_t combinedLen = rawLen;
  const uint16_t crc =
      crcOverScope(reinterpret_cast<const uint8_t*>(verb), std::strlen(verb),
                   raw, rawLen);
  if (!WireRuntime::encodeCrc16(crc, combined, sizeof(combined), &combinedLen)) {
    return false;
  }

  uint8_t cobs[kV5FrameMax];
  size_t cobsLen = 0;
  if (!WireRuntime::cobsEncode(combined, combinedLen, cobs, sizeof(cobs),
                               &cobsLen, kV5CobsDelimiter)) {
    return false;
  }

  uint8_t line[32 + kV5FrameMax + 1];
  const size_t verbLen = std::strlen(verb);
  if (verbLen + 1 + cobsLen + 1 > sizeof(line)) return false;
  std::memcpy(line, verb, verbLen);
  line[verbLen] = ':';
  std::memcpy(line + verbLen + 1, cobs, cobsLen);
  line[verbLen + 1 + cobsLen] = '\n';
  const size_t totalLen = verbLen + 1 + cobsLen + 1;
  if (viaUdp) {
    return RobotWifi::sendV5Datagram(line, totalLen);
  }
  return RobotWifi::writeToSocket(line, totalLen);
}

// Thin TCP-only wrappers: the modal REPL's own banner/ack strings
// ("[V5 mode]...", "OK:leaving-v5", TLM stream toggles) never go over UDP.
bool sendWifiLine(const char* line) { return emitWifiLine(false, line); }
bool sendWifiFrame(const char* verb, const msg::ReplyEnvelope& reply) {
  return emitWifiFrame(false, verb, reply);
}

bool decodeCommandFrame(const char* verb, const uint8_t* frame, size_t frameLen,
                        msg::CommandEnvelope* out) {
  uint8_t combined[msg::wire::kCommandEnvelopeMaxEncodedSize + 2];
  size_t combinedLen = 0;
  if (!WireRuntime::cobsDecode(frame, frameLen, combined, sizeof(combined),
                               &combinedLen, kV5CobsDelimiter)) {
    return false;
  }
  if (combinedLen < 2) return false;
  const size_t payloadLen = combinedLen - 2;
  size_t crcPos = payloadLen;
  uint16_t receivedCrc = 0;
  if (!WireRuntime::decodeCrc16(combined, combinedLen, &crcPos, &receivedCrc)) {
    return false;
  }
  const uint16_t expected =
      crcOverScope(reinterpret_cast<const uint8_t*>(verb), std::strlen(verb),
                   combined, payloadLen);
  if (expected != receivedCrc) return false;
  const msg::wire::Result result =
      msg::wire::decode(*out, combined, static_cast<uint16_t>(payloadLen));
  return result.ok;
}

void sendAck(bool viaUdp, uint32_t corrId, uint32_t q, float rem, uint32_t t) {
  msg::ReplyEnvelope reply;
  reply.body_kind = msg::ReplyEnvelope::BodyKind::OK;
  reply.corr_id = corrId;
  reply.body.ok.q = q;
  reply.body.ok.rem = rem;
  reply.body.ok.t = t;
  emitWifiFrame(viaUdp, "OK", reply);
}

void sendError(bool viaUdp, uint32_t corrId, msg::ErrCode code,
              uint32_t field = 0) {
  msg::ReplyEnvelope reply;
  reply.body_kind = msg::ReplyEnvelope::BodyKind::ERR;
  reply.corr_id = corrId;
  reply.body.err.code = code;
  reply.body.err.field = field;
  emitWifiFrame(viaUdp, "ERR", reply);
}

void sendTelemetry(bool viaUdp, uint32_t seq, uint32_t ackWord) {
  float leftPos = 0.0f;
  float rightPos = 0.0f;
  dt().wheelPositions(leftPos, rightPos);

  float x = 0.0f;
  float y = 0.0f;
  float h = 0.0f;
  otos().read(x, y, h);

  uint32_t lineReading[4] = {};
  line().read(lineReading);

  uint32_t rv = 0;
  uint32_t gv = 0;
  uint32_t bv = 0;
  uint32_t cv = 0;
  color().read(rv, gv, bv, cv);

  msg::ReplyEnvelope reply;
  reply.body_kind = msg::ReplyEnvelope::BodyKind::TLM;
  reply.body.tlm.now = mp_hal_ticks_ms();
  reply.body.tlm.seq = seq;
  reply.body.tlm.mode = msg::DriveMode::VELOCITY;
  reply.body.tlm.flags = kFlagActive | kFlagReady |
                         kFlagConnLeft | kFlagConnRight |
                         kFlagOtosPresent | kFlagOtosConnected |
                         kFlagLinePresent | kFlagLineFresh |
                         kFlagColorPresent | kFlagColorFresh;
  reply.body.tlm.enc_left.position = msg::EncoderReading::packPosition(leftPos);
  reply.body.tlm.enc_right.position =
      msg::EncoderReading::packPosition(rightPos);
  reply.body.tlm.otos.x = msg::OtosReading::packX(x);
  reply.body.tlm.otos.y = msg::OtosReading::packY(y);
  reply.body.tlm.otos.heading = msg::OtosReading::packHeading(h);
  reply.body.tlm.pose.x = msg::Pose2D::packX(x);
  reply.body.tlm.pose.y = msg::Pose2D::packY(y);
  reply.body.tlm.pose.h = msg::Pose2D::packH(h);
  reply.body.tlm.line = packLine(lineReading);
  reply.body.tlm.color = packColor(rv, gv, bv, cv);
  reply.body.tlm.acks_[0] = ackWord;
  reply.body.tlm.acks_count = 1;
  reply.body.tlm.cycle_period = kWifiCyclePeriodUs;
  emitWifiFrame(viaUdp, "TLM", reply);
}

// wheels.duration is [ms] per the wire contract (envelope.proto's `Wheels`:
// "float duration = 3; // [ms] REQUIRED hold window; <=0 -> ERR_BADARG") --
// NOT seconds. A prior version multiplied by 1000 here as though converting
// seconds->ms, which turned rogo's `wheels 80 80 500` (500 ms) into a
// mp_hal_delay_ms(500000) 500-SECOND freeze (measured on the wedged board via
// gdb) -- the incident that ran gopiv's wheels for 8+ minutes unsupervised
// (2026-08-14 night). duration<=0 means no motion at all, matching
// ERR_BADARG semantics -- the dispatcher's caller (dispatchV5Line) still
// sends its ack either way, so this just declines to stage or run anything.
// Whatever survives that check is also hard-clamped to kMaxWheelsWindowMs
// (see its own comment) -- a single exploratory WHEELS frame must never be
// able to buy more than that much unsupervised motion, whatever units bug
// or fat-fingered value produced the requested duration.
//
// Ctrl-c handling: dt().runDutyWindow() NEVER raises (see its own comment
// for the full reasoning) -- it stops the motors and reports whether ctrl-c
// fired. handleWheels() is reachable both from the TCP v5 REPL
// (serviceWifiV5, inside robot.enter_v5()'s own Python call frame --
// raising would be safe there) and from the always-on UDP v5 engine
// (robot_v5_service(), invoked from microbit_hal_background_processing() on
// the VM hook -- raising is NOT safe there, since nothing guarantees a live
// Python call frame owns that context). Because this function cannot tell
// which of those two callers it is running under, it never raises either:
// the motors are already stopped by runDutyWindow() by the time this
// returns, which is the part that actually matters for safety, so a ctrl-c
// here is simply dropped rather than propagated.
void handleWheels(const msg::Wheels& wheels) {
  if (wheels.duration <= 0.0f) {
    return;
  }
  const float leftDuty = clampf(wheels.v_left * kDutyPerSpeed, -1.0f, 1.0f);
  const float rightDuty = clampf(wheels.v_right * kDutyPerSpeed, -1.0f, 1.0f);
  const uint32_t requestedMs = static_cast<uint32_t>(wheels.duration);
  const uint32_t durationMs =
      requestedMs > kMaxWheelsWindowMs ? kMaxWheelsWindowMs : requestedMs;
  (void)dt().runDutyWindow(leftDuty, rightDuty, durationMs);
}

// viaUdp mirrors dispatchV5Line()'s own parameter: false means this call
// came through serviceWifiV5() inside robot.enter_v5()'s Python call frame
// (safe to raise); true means it came through robot_v5_service()'s
// background dispatch (invoked from microbit_hal_background_processing()
// on the VM hook -- NOT safe to raise, since no Python call frame
// necessarily owns that context; same reasoning as handleWheels()'s own
// comment, 2026-08-14 gopiv incident follow-up). allowRaise is the
// motion-domain form of that same fact, threaded down into every run*
// helper this dispatches to.
void handleMove(const msg::Move& move, bool viaUdp) {
  const bool allowRaise = !viaUdp;
  const uint32_t timeoutMs = static_cast<uint32_t>(
      (move.timeout > 0.0f ? move.timeout : 3.0f) * 1000.0f);
  switch (move.velocity_kind) {
    case msg::Move::VelocityKind::TWIST: {
      const float vx = move.velocity.twist.v_x;
      const float omega = move.velocity.twist.omega;
      switch (move.stop_kind) {
        case msg::Move::StopKind::DISTANCE:
          (void)runMoveDistance(vx, omega, move.stop.distance, timeoutMs,
                                allowRaise);
          return;
        case msg::Move::StopKind::ANGLE:
          (void)runTurnAngle(omega == 0.0f ? kDefaultTurnOmega : fabsf(omega),
                             move.stop.angle, timeoutMs, allowRaise);
          return;
        case msg::Move::StopKind::TIME: {
          // move.stop.time is [ms] per the wire contract (envelope.proto's
          // Move: "float time = 3; // [ms] elapsed since activation") --
          // NOT seconds. This branch used to multiply by 1000 here, the
          // exact same units bug as the WHEELS incident this file's
          // kMaxWheelsWindowMs/runDutyWindow() exist to fix (2026-08-14
          // gopiv: an 8+ minute unsupervised run) -- a 500 ms hold became
          // mp_hal_delay_ms(500000), and it did so with a BARE delay that
          // never re-ticks the polled motors, so the staged duty never
          // reached the bus past the single tick inside
          // setDutyCommand(). Route this through runDutyWindow() instead:
          // it ticks every pass (duty actually reaches the I2C bus) and is
          // hard-bounded to this Move's own timeoutMs -- the REQUIRED
          // safety backstop every other stop condition here is already
          // held to.
          float leftDuty = 0.0f;
          float rightDuty = 0.0f;
          twistToDuty(vx, omega, leftDuty, rightDuty);
          const uint32_t requestedMs =
              static_cast<uint32_t>(fmaxf(0.0f, move.stop.time));
          const uint32_t durationMs =
              requestedMs > timeoutMs ? timeoutMs : requestedMs;
          const bool interrupted =
              dt().runDutyWindow(leftDuty, rightDuty, durationMs);
          if (interrupted && allowRaise) {
            mp_raise_type(&mp_type_KeyboardInterrupt);
          }
          return;
        }
        default:
          dt().stopMotors();
          return;
      }
    }
    case msg::Move::VelocityKind::WHEELS: {
      msg::Wheels wheels;
      wheels.v_left = move.velocity.wheels.v_left;
      wheels.v_right = move.velocity.wheels.v_right;
      wheels.duration =
          move.stop_kind == msg::Move::StopKind::TIME ? move.stop.time : 0.0f;
      handleWheels(wheels);
      return;
    }
    default:
      dt().stopMotors();
      return;
  }
}

// viaUdp mirrors handleMove()'s own parameter -- see its comment for the
// full reasoning.
void handleGoTo(const msg::GoTo& goTo, bool viaUdp) {
  (void)runGoTo(goTo.x, goTo.y, static_cast<int>(goTo.frame), goTo.speed,
               goTo.arrive, static_cast<uint32_t>(
                                (goTo.timeout > 0.0f ? goTo.timeout : 5.0f) *
                                1000.0f),
               /*allowRaise=*/!viaUdp);
}

// Shared v5 wire dispatch, used by BOTH planes: the TCP REPL's modal loop
// (serviceWifiV5, viaUdp=false -- replies go through the TCP coalescer
// unchanged) and the always-on UDP v5 engine (robot_v5_service, viaUdp=true
// -- each reply is one datagram via RobotWifi::sendV5Datagram). Handles
// everything protocol-v5 itself defines: the cleartext verbs (HELLO/PING/
// ID/VER/STATUS) and the binary command plane (STOP/ESTOP/WHEELS/MOVE/
// GO_TO) -- decode, dispatch, ack, and one telemetry frame carrying the
// ack word. Modal-REPL-only conveniences ("TLM" bare, "TLM:1"/"TLM:0"
// stream toggle, "REPL" exit) are NOT here -- serviceWifiV5 intercepts
// those itself before falling through to this function; the UDP engine has
// no equivalent (its telemetry is always-on, never opt-in).
void dispatchV5Line(const char* line, size_t len, bool viaUdp,
                    uint32_t& seq) {
  const char* separator =
      static_cast<const char*>(std::memchr(line, ':', len));
  if (separator == nullptr) {
    if (std::strcmp(line, "HELLO") == 0) {
      // DEVICE:NEZHA2:robot:<name>:<serial> -- byte-frozen banner shape,
      // src/firm/platform/microbit/microbit_banner.cpp's formatBanner().
      // The old 3-field "DEVICE:NEZHA2:MICROPY-WIFI" had too few
      // colon-fields for serial_conn.py's _parse_device_banner() (requires
      // >= 5), so rogo reported "No device found" even though this plane
      // answered every HELLO correctly.
      char banner[64];
      std::snprintf(banner, sizeof(banner), "DEVICE:NEZHA2:robot:%s:%lu\n",
                    codal::microbit_friendly_name(),
                    static_cast<unsigned long>(codal::microbit_serial_number()));
      emitWifiLine(viaUdp, banner);
    } else if (std::strcmp(line, "PING") == 0) {
      char pongLine[32];
      std::snprintf(pongLine, sizeof(pongLine), "PONG:t=%lu\n",
                    static_cast<unsigned long>(mp_hal_ticks_ms()));
      emitWifiLine(viaUdp, pongLine);
    } else if (std::strcmp(line, "ID") == 0) {
      // ID:<drivetrainType>:<profileName>:<version> -- formatIdLine()'s
      // 4-field shape. This exploration image has no baked drivetrain/
      // profile config, so drivetrainType is the fixed "differential"
      // constant (the only drivetrain modrobot.cpp's Drivetrain drives) and
      // profileName is the device's own friendly name.
      char idLine[64];
      std::snprintf(idLine, sizeof(idLine), "ID:differential:%s:micropython\n",
                    codal::microbit_friendly_name());
      emitWifiLine(viaUdp, idLine);
    } else if (std::strcmp(line, "VER") == 0) {
      emitWifiLine(viaUdp, "VER:micropython\n");
    } else if (std::strcmp(line, "STATUS") == 0) {
      emitWifiLine(viaUdp, "STATUS:mode=v5 transport=wifi\n");
    } else {
      sendError(viaUdp, 0, msg::ErrCode::ERR_BADARG);
    }
    return;
  }

  const size_t verbLen = static_cast<size_t>(separator - line);
  const msg::VerbEntry* entry = findVerb(line, verbLen);
  if (entry == nullptr || !entry->binary) {
    sendError(viaUdp, 0, msg::ErrCode::ERR_BADARG);
    return;
  }

  msg::CommandEnvelope env;
  const uint8_t* frame = reinterpret_cast<const uint8_t*>(separator + 1);
  const size_t frameLen = len - verbLen - 1;
  if (!decodeCommandFrame(entry->name, frame, frameLen, &env)) {
    sendError(viaUdp, 0, msg::ErrCode::ERR_DECODE);
    return;
  }

  const uint32_t corrId = env.corr_id;
  uint32_t q = 0;
  switch (env.cmd_kind) {
    case msg::CommandEnvelope::CmdKind::STOP:
      dt().stopMotors();
      q = env.cmd.stop.id;
      break;
    case msg::CommandEnvelope::CmdKind::ESTOP:
      dt().stopMotors();
      q = 0;
      break;
    case msg::CommandEnvelope::CmdKind::WHEELS:
      handleWheels(env.cmd.wheels);
      q = env.cmd.wheels.id;
      break;
    case msg::CommandEnvelope::CmdKind::MOVE:
      // NOTE: handleMove() blocks for the whole move (mp_hal_delay_ms /
      // encoder-polled busy-waits) -- from the UDP engine this stalls the
      // REPL and the TCP v5 mode too, since all three share one main
      // fiber. Accepted for this exploration image. viaUdp is forwarded
      // so handleMove() knows whether raising an exception on ctrl-c/
      // timeout is safe here (see its own comment).
      handleMove(env.cmd.move, viaUdp);
      q = env.cmd.move.id;
      break;
    case msg::CommandEnvelope::CmdKind::GO_TO:
      handleGoTo(env.cmd.go_to, viaUdp);
      q = env.cmd.go_to.id;
      break;
    default:
      sendError(viaUdp, corrId, msg::ErrCode::ERR_UNIMPLEMENTED);
      return;
  }
  sendAck(viaUdp, corrId, q, 0.0f, mp_hal_ticks_ms());
  const uint32_t ackWord =
      (corrId << 4) | static_cast<uint32_t>(msg::ErrCode::ERR_NONE);
  sendTelemetry(viaUdp, seq++, ackWord);
}

void serviceWifiV5() {
  if (!RobotWifi::connected()) {
    mp_raise_msg(&mp_type_RuntimeError,
                 MP_ERROR_TEXT("wifi socket not connected"));
  }

  sendWifiLine(
      "\r\n[V5 mode] REPL to exit; TLM for one frame; TLM:1 / TLM:0 stream on/off\r\n");

  uint8_t rxByte = 0;
  char lineBuf[kV5LineBuffer] = {};
  size_t lineLen = 0;
  uint32_t seq = 0;
  uint32_t lastTlm = mp_hal_ticks_ms();
  // Telemetry is OPT-IN (stakeholder 2026-08-14): the default stream buried
  // the interactive session in TLM frames. Bare "TLM" = one frame now;
  // "TLM:1" starts the stream; "TLM:0" stops it. (The UDP v5 engine does
  // NOT have this opt-in -- its telemetry is always on; see
  // robot_v5_service.)
  bool tlmStream = false;

  while (RobotWifi::connected()) {
    RobotWifi::service();
    RobotWifi::flushOutput();  // main context: push coalesced replies/TLM out
    if (RobotWifi::read(&rxByte, 1) == 1) {
      if (rxByte == '\n') {
        // Strip at most one trailing CR here, at line-terminate time --
        // NOT during assembly. 0x0D is a legitimate payload byte inside a
        // COBS-encoded protocol-v5 binary frame (delimiter 0x0A), so it
        // must be buffered like any other byte. The host's own binary
        // frames end on a bare '\n' with no trailing CR, so this can only
        // ever strip a real interactive client's CRLF, never a byte from
        // inside a frame.
        if (lineLen > 0 && lineBuf[lineLen - 1] == '\r') {
          --lineLen;
        }
        if (lineLen == 0) {
          continue;
        }
        lineBuf[lineLen] = '\0';
        if (std::strcmp(lineBuf, "REPL") == 0) {
          sendWifiLine("OK:leaving-v5\n");
          dt().stopMotors();
          return;
        }
        if (std::strcmp(lineBuf, "TLM") == 0) {
          sendTelemetry(/*viaUdp=*/false, seq++, 0);
          lineLen = 0;
          lastTlm = mp_hal_ticks_ms();
          continue;
        }
        if (std::strcmp(lineBuf, "TLM:1") == 0) {
          tlmStream = true;
          sendWifiLine("OK:tlm-stream-on\n");
          lineLen = 0;
          lastTlm = mp_hal_ticks_ms();
          continue;
        }
        if (std::strcmp(lineBuf, "TLM:0") == 0) {
          tlmStream = false;
          sendWifiLine("OK:tlm-stream-off\n");
          lineLen = 0;
          continue;
        }

        dispatchV5Line(lineBuf, lineLen, /*viaUdp=*/false, seq);
        lineLen = 0;
        lastTlm = mp_hal_ticks_ms();
        continue;
      }
      if (lineLen + 1 < sizeof(lineBuf)) {
        lineBuf[lineLen++] = static_cast<char>(rxByte);
      } else {
        lineLen = 0;
        sendError(/*viaUdp=*/false, 0, msg::ErrCode::ERR_OVERSIZE);
      }
    }
    if (tlmStream && mp_hal_ticks_ms() - lastTlm >= kWifiTlmPeriodMs) {
      sendTelemetry(/*viaUdp=*/false, seq++, 0);
      lastTlm = mp_hal_ticks_ms();
    }
    // serviceWifiV5() only ever runs inside robot.enter_v5()'s own Python
    // call frame (robot_enter_v5_fn -> serviceWifiV5, direct call, no
    // background dispatch involved) -- always safe to raise.
    maybeCtrlC(/*allowRaise=*/true);
    mp_hal_delay_ms(1);
  }

  dt().stopMotors();
  mp_raise_msg(&mp_type_RuntimeError,
               MP_ERROR_TEXT("wifi socket disconnected"));
}

}  // namespace

extern "C" {

mp_obj_t robot_move_fn(size_t n_args, const mp_obj_t* args) {
  const float vX = mp_obj_get_float(args[0]);
  const float omega = mp_obj_get_float(args[1]);
  const float distance = mp_obj_get_float(args[2]);
  const uint32_t timeoutMs = static_cast<uint32_t>(mp_obj_get_int(args[3]));
  // Direct Python call frame -- always safe to raise; this is exactly the
  // case runMoveDistance()'s own comment calls the "always safe" path.
  (void)runMoveDistance(vX, omega, distance, timeoutMs, /*allowRaise=*/true);
  return makePoseTuple();
}

mp_obj_t robot_turn_fn(size_t n_args, const mp_obj_t* args) {
  const float omega = mp_obj_get_float(args[0]);
  const float angle = mp_obj_get_float(args[1]);
  const uint32_t timeoutMs = static_cast<uint32_t>(mp_obj_get_int(args[2]));
  (void)runTurnAngle(omega, angle, timeoutMs, /*allowRaise=*/true);
  return makePoseTuple();
}

mp_obj_t robot_go_to_fn(size_t n_args, const mp_obj_t* args) {
  const float x = mp_obj_get_float(args[0]);
  const float y = mp_obj_get_float(args[1]);
  const int frame = parseFrame(args[2]);
  const float speed = mp_obj_get_float(args[3]);
  const float arrive = mp_obj_get_float(args[4]);
  const uint32_t timeoutMs = static_cast<uint32_t>(mp_obj_get_int(args[5]));
  (void)runGoTo(x, y, frame, speed, arrive, timeoutMs, /*allowRaise=*/true);
  return makePoseTuple();
}

mp_obj_t robot_move_wheels_fn(mp_obj_t leftObj, mp_obj_t rightObj, mp_obj_t msObj) {
  const int left = mp_obj_get_int(leftObj);
  const int right = mp_obj_get_int(rightObj);
  const uint32_t ms = static_cast<uint32_t>(mp_obj_get_int(msObj));
  dt().driveWheelPct(left, right, ms == 0 ? kDefaultMoveMs : ms);
  return makeEncoderTuple();
}

mp_obj_t robot_drive_wheels_fn(mp_obj_t leftObj, mp_obj_t rightObj) {
  return robot_move_wheels_fn(leftObj, rightObj, mp_obj_new_int(kDefaultMoveMs));
}

mp_obj_t robot_set_wheels_fn(mp_obj_t leftObj, mp_obj_t rightObj) {
  const int left = mp_obj_get_int(leftObj);
  const int right = mp_obj_get_int(rightObj);
  const float leftDuty = clampf(static_cast<float>(left) / 100.0f, -1.0f, 1.0f);
  const float rightDuty = clampf(static_cast<float>(right) / 100.0f, -1.0f, 1.0f);
  dt().setDutyCommand(leftDuty, rightDuty);
  return makeEncoderTuple();
}

mp_obj_t robot_stop_fn(void) {
  dt().stopMotors();
  return makeEncoderTuple();
}

mp_obj_t robot_encoders_fn(void) {
  return makeEncoderTuple();
}

mp_obj_t robot_otos_fn(void) {
  return makePoseTuple();
}

mp_obj_t robot_line_fn(void) {
  uint32_t ch[4] = {};
  line().read(ch);
  mp_obj_t items[4] = {
      mp_obj_new_int(ch[0]), mp_obj_new_int(ch[1]),
      mp_obj_new_int(ch[2]), mp_obj_new_int(ch[3]),
  };
  return mp_obj_new_tuple(4, items);
}

mp_obj_t robot_color_fn(void) {
  uint32_t rv = 0, gv = 0, bv = 0, cv = 0;
  color().read(rv, gv, bv, cv);
  mp_obj_t items[4] = {
      mp_obj_new_int(rv), mp_obj_new_int(gv),
      mp_obj_new_int(bv), mp_obj_new_int(cv),
  };
  return mp_obj_new_tuple(4, items);
}

mp_obj_t robot_servo_fn(mp_obj_t portObj, mp_obj_t angleObj) {
  const int port = mp_obj_get_int(portObj);
  const int angle = mp_obj_get_int(angleObj);
  const int pinIdx = servoPin(port);
  if (pinIdx < 0) {
    mp_raise_ValueError(MP_ERROR_TEXT("servo port must be 1..4"));
  }
  const int clamped = angle < 0 ? 0 : (angle > 180 ? 180 : angle);
  const int pulseUs = 1000 + (clamped * 1000 / 180);
  const int value = (pulseUs * 1023 + 10000) / 20000;
  microbit_hal_pin_set_analog_period_us(pinIdx, 20000);
  microbit_hal_pin_write_analog_u10(pinIdx, value);
  return mp_const_none;
}

mp_obj_t robot_enter_v5_fn(void) {
  serviceWifiV5();
  return mp_const_none;
}

mp_obj_t robot_ping_fn(void) {
  // Liveness without the v5 modal switch: returns uptime. [ms]
  return mp_obj_new_int_from_uint(mp_hal_ticks_ms());
}

mp_obj_t robot_tlm_fn(void) {
  // One telemetry snapshot on demand -- the same sources the v5 TLM frame
  // reads, as a dict, instead of a binary stream.
  float leftPos = 0.0f;
  float rightPos = 0.0f;
  dt().wheelPositions(leftPos, rightPos);

  float x = 0.0f;
  float y = 0.0f;
  float h = 0.0f;
  otos().read(x, y, h);

  uint32_t lineReading[4] = {};
  line().read(lineReading);

  uint32_t rv = 0;
  uint32_t gv = 0;
  uint32_t bv = 0;
  uint32_t cv = 0;
  color().read(rv, gv, bv, cv);

  mp_obj_t dict = mp_obj_new_dict(5);
  mp_obj_dict_store(dict, mp_obj_new_str("t", 1),
                    mp_obj_new_int_from_uint(mp_hal_ticks_ms()));
  mp_obj_t enc[2] = {mp_obj_new_float(leftPos), mp_obj_new_float(rightPos)};
  mp_obj_dict_store(dict, mp_obj_new_str("enc", 3), mp_obj_new_tuple(2, enc));
  mp_obj_t pose[3] = {mp_obj_new_float(x), mp_obj_new_float(y),
                      mp_obj_new_float(h)};
  mp_obj_dict_store(dict, mp_obj_new_str("pose", 4), mp_obj_new_tuple(3, pose));
  mp_obj_t lineVals[4] = {
      mp_obj_new_int_from_uint(lineReading[0]),
      mp_obj_new_int_from_uint(lineReading[1]),
      mp_obj_new_int_from_uint(lineReading[2]),
      mp_obj_new_int_from_uint(lineReading[3])};
  mp_obj_dict_store(dict, mp_obj_new_str("line", 4),
                    mp_obj_new_tuple(4, lineVals));
  mp_obj_t colorVals[4] = {
      mp_obj_new_int_from_uint(rv), mp_obj_new_int_from_uint(gv),
      mp_obj_new_int_from_uint(bv), mp_obj_new_int_from_uint(cv)};
  mp_obj_dict_store(dict, mp_obj_new_str("color", 5),
                    mp_obj_new_tuple(4, colorVals));
  return dict;
}

mp_obj_t robot_wifi_status_fn(void) {
  char status[256];  // full debugStatus() line runs past 128 with cmd=/reply=
  RobotWifi::debugStatus(status, sizeof(status));
  return mp_obj_new_str(status, std::strlen(status));
}

// robot_v5_service -- the ALWAYS-ON v5 UDP engine. Not Python-callable (no
// qstr, no mp_obj_t binding): the vendored tree calls this directly from
// main-context call sites (mphalport.cpp's stdin wait loop and
// mp_hal_stdio_poll, plus microbit_hal_background_processing() -- the
// reentrancy guard below is what makes that last one safe, since it runs
// from the VM hook on every N bytecodes). It pumps whatever the v5 UDP
// socket (wifi_stdio.cpp's link kV5Link) has received, dispatches complete
// lines through the SAME dispatchV5Line() the TCP v5 mode uses, and pushes
// an always-on telemetry stream to whichever peer last spoke -- the
// protocol-v5 contract rogo/the host tools expect, independent of whether
// anyone is also using the interactive TCP REPL.
void robot_v5_service(void) {
  static bool inProgress = false;
  if (inProgress) {
    // Re-entered from inside a blocking command THIS function itself
    // dispatched (handleMove() -> mp_hal_delay_ms -> the VM hook ->
    // microbit_hal_background_processing -> here again). The outer call
    // still owns lineBuf/lineLen below; recursing into the line parser
    // here would corrupt whatever line is in flight.
    return;
  }
  inProgress = true;

  // Boot-time zero write, forced as early as this module has any hook for
  // it (2026-08-14 gopiv/vevov runaway -- see Drivetrain::ensureStarted()'s
  // own comment for what this actually writes and why it is provably a
  // real I2C write, not a no-op). modrobot_glue.c has no module
  // import-time init to attach this to -- it is just a const function
  // table (robot.* are plain functions; nothing runs at `import robot`
  // time) -- so this is the earliest call site this file has:
  // robot_v5_service() is invoked from main-context call sites
  // (mphalport.cpp's stdin wait loop, mp_hal_stdio_poll) before any WHEELS
  // command, v5 peer, or even a Python call into the robot module has
  // necessarily happened. Forcing ensureStarted() here on this function's
  // very first call -- rather than waiting on the ordinary lazy
  // ensureStarted() already present in every other Drivetrain method --
  // closes the window between boot and the first deliberate motion command
  // during which a latched brick could otherwise keep spinning unnoticed.
  static bool driveStarted = false;
  if (!driveStarted) {
    dt().ensureStarted();
    driveStarted = true;
  }

  static char lineBuf[kV5LineBuffer] = {};
  static size_t lineLen = 0;
  static uint32_t seq = 0;
  static uint32_t lastTlm = 0;
  static bool hadPeer = false;

  uint8_t rxByte = 0;
  while (RobotWifi::readV5(&rxByte, 1) == 1) {
    if (rxByte == '\n') {
      // Strip at most one trailing CR here, at line-terminate time -- NOT
      // during assembly. 0x0D is a legitimate payload byte inside a
      // COBS-encoded protocol-v5 binary frame (delimiter 0x0A), so it must
      // be buffered like any other byte. The host's own binary frames end
      // on a bare '\n' with no trailing CR, so this can only ever strip a
      // real interactive client's CRLF, never a byte from inside a frame.
      if (lineLen > 0 && lineBuf[lineLen - 1] == '\r') {
        --lineLen;
      }
      if (lineLen == 0) continue;  // empty line = keepalive; ignore silently
      lineBuf[lineLen] = '\0';
      dispatchV5Line(lineBuf, lineLen, /*viaUdp=*/true, seq);
      lineLen = 0;
      continue;
    }
    if (lineLen + 1 < sizeof(lineBuf)) {
      lineBuf[lineLen++] = static_cast<char>(rxByte);
    } else {
      lineLen = 0;
      sendError(/*viaUdp=*/true, 0, msg::ErrCode::ERR_OVERSIZE);
    }
  }

  // New-peer detection: RobotWifi captures the peer address off ANY inbound
  // link-kV5Link datagram (wifi_stdio.cpp's IpdParser under CIPDINFO=1), so
  // v5PeerKnown() flips false->true on the very first byte the host ever
  // sends -- which is always a HELLO (robot_radio.io.udp_link.UdpLink.
  // discover()'s retry loop). dispatchV5Line() above already answered that
  // HELLO with the usual DEVICE: banner; this adds the unsolicited READY
  // line SerialConnection.connect() separately waits up to 10s for
  // (serial_conn.py's _wait_for_ready), once per new peer -- not resent
  // again until the peer is forgotten (60s silence) and rediscovered.
  const bool peerNow = RobotWifi::v5PeerKnown();
  if (peerNow && !hadPeer) {
    emitWifiLine(/*viaUdp=*/true, "READY\n");
  }
  hadPeer = peerNow;

  // Always-on TLM push -- the v5 plane's contract (rogo needs a live stream
  // with no opt-in). This does NOT touch the TCP REPL's TLM:1/TLM:0 toggle
  // (serviceWifiV5's own tlmStream, above): the two planes' telemetry
  // policies are independent on purpose.
  if (peerNow && mp_hal_ticks_ms() - lastTlm >= kWifiTlmPeriodMs) {
    sendTelemetry(/*viaUdp=*/true, seq++, 0);
    lastTlm = mp_hal_ticks_ms();
  }

  inProgress = false;
}

}  // extern "C"
