# robot.py -- Pure-Python Nezha V2 motor driver for MicroPython on micro:bit V2.
#
# Works on the STOCK MicroPython v2.1.2 hex with NO build changes.
# Flash the stock hex, connect via USB REPL (mpremote or screen), then:
#
#   from robot import drive, stop
#   drive(50, 50)   # forward 50%
#   stop()
#
# HARDWARE (tovez / classroom-bot):
#   Nezha V2 motor board  I2C addr 0x10, I2C bus on P19/P20 (edge connector)
#   Left  wheel: port 1, fwd_sign=+1  (CW  = forward)
#   Right wheel: port 2, fwd_sign=-1  (CCW = forward)
#
# PROTOCOL (from Hardware::NezhaMotor::writeMotorRun):
#   Write 8 bytes to 0x10:
#     [0xFF, 0xF9, port, direction, 0x60, speed, 0xF5, 0x00]
#   direction: 1=CW, 2=CCW
#   speed:     0..100 (percent)
#
# PORT NUMBERS:
#   Nezha V2 has 4 motor ports.  Ports 1/2 are the drive pair for tovez.
#   Change LEFT_PORT / RIGHT_PORT below to match your robot.

from microbit import i2c

LEFT_PORT  = 1
RIGHT_PORT = 2

_NEZHA_ADDR = 0x10
_DIR_CW  = 1
_DIR_CCW = 2


def _write_motor(port, direction, speed):
    speed = max(0, min(100, speed))
    i2c.write(_NEZHA_ADDR, bytes([0xFF, 0xF9, port, direction, 0x60, speed, 0xF5, 0x00]))


def _left(pct):
    """pct: -100..100, positive=forward (fwd_sign=+1)"""
    if pct >= 0:
        _write_motor(LEFT_PORT, _DIR_CW, abs(pct))
    else:
        _write_motor(LEFT_PORT, _DIR_CCW, abs(pct))


def _right(pct):
    """pct: -100..100, positive=forward (fwd_sign=-1 inverts physical dir)"""
    if pct >= 0:
        _write_motor(RIGHT_PORT, _DIR_CCW, abs(pct))
    else:
        _write_motor(RIGHT_PORT, _DIR_CW, abs(pct))


def drive(left_pct, right_pct):
    """Drive both wheels. Values -100..100, positive=forward."""
    _left(left_pct)
    _right(right_pct)


def stop():
    """Coast stop both wheels."""
    _write_motor(LEFT_PORT,  _DIR_CW, 0)
    _write_motor(RIGHT_PORT, _DIR_CW, 0)


def forward(pct=50):
    drive(pct, pct)

def backward(pct=50):
    drive(-pct, -pct)

def turn_left(pct=50):
    drive(-pct, pct)

def turn_right(pct=50):
    drive(pct, -pct)
