/*
 * modrobot.c -- MicroPython C module: robot
 *
 * Exposes bare Nezha V2 motor commands to Python without going through the
 * microbit.i2c Python object.  Goes in src/codal_port/ alongside the other
 * mod*.c files.
 *
 * API (Phase A spike -- enough to prove "send command, wheel moves"):
 *
 *   import robot
 *   robot.drive(left_pct, right_pct)   # -100..100, positive=forward
 *   robot.stop()
 *   robot.encoders()                   # (left_counts, right_counts)
 *
 * WIRING INTO THE BUILD:
 *   1. Copy this file to micropython-microbit-v2/src/codal_port/modrobot.c
 *   2. Add "modrobot.c \" to SRC_C in codal_port/Makefile
 *   3. In mpconfigport.h, add:
 *        extern const struct _mp_obj_module_t robot_module;
 *      and in MICROPY_PORT_BUILTIN_MODULES:
 *        { MP_ROM_QSTR(MP_QSTR_robot), MP_ROM_PTR(&robot_module) }, \
 *
 * NOTES:
 *   - Calls microbit_hal_i2c_writeto() directly (declared in microbithal.h).
 *     That function calls uBit.i2c.write(addr<<1, ...) -- same bus the
 *     Nezha board is on (P19/P20 edge connector).
 *   - Hardcodes port 1=left (fwd_sign=+1) and port 2=right (fwd_sign=-1)
 *     for tovez.  Caller passes -100..100; negative fwd_sign is applied here.
 *   - Encoder reads are exposed here only as a minimal verification hook for
 *     the spike.  The full kernel integration will own sampling/clearance.
 */

#include "py/runtime.h"
#include "microbithal.h"

#define NEZHA_ADDR  (0x10)
#define DIR_CW      (1)
#define DIR_CCW     (2)
#define LEFT_PORT   (1)
#define RIGHT_PORT  (2)

static int32_t nezha_read_encoder(int port) {
    uint8_t cmd[8] = {
        0xFF, 0xF9,
        (uint8_t)port,
        0x00,
        0x46,
        0x00,
        0xF5,
        0x00,
    };
    uint8_t resp[4] = { 0, 0, 0, 0 };

    if (microbit_hal_i2c_writeto(NEZHA_ADDR, cmd, 8, true) != 0) {
        return 0;
    }
    if (microbit_hal_i2c_readfrom(NEZHA_ADDR, resp, 4, true) != 0) {
        return 0;
    }

    return (int32_t)(
        ((uint32_t)resp[3] << 24) |
        ((uint32_t)resp[2] << 16) |
        ((uint32_t)resp[1] << 8) |
        (uint32_t)resp[0]
    );
}

/* Write one 8-byte Nezha motor command frame. */
static void nezha_write(int port, int direction, int speed) {
    if (speed < 0)   speed = 0;
    if (speed > 100) speed = 100;
    uint8_t buf[8] = {
        0xFF, 0xF9,
        (uint8_t)port,
        (uint8_t)direction,
        0x60,
        (uint8_t)speed,
        0xF5,
        0x00
    };
    microbit_hal_i2c_writeto(NEZHA_ADDR, buf, 8, true);
}

/*
 * robot.drive(left_pct, right_pct)
 * Each value: -100..100 integer percent, positive=forward.
 * Left  (port 1, fwd_sign=+1): positive duty -> CW
 * Right (port 2, fwd_sign=-1): positive duty -> CCW (sign inversion here)
 */
STATIC mp_obj_t robot_drive(mp_obj_t left_obj, mp_obj_t right_obj) {
    int left  = mp_obj_get_int(left_obj);
    int right = mp_obj_get_int(right_obj);

    /* left wheel */
    if (left >= 0) {
        nezha_write(LEFT_PORT, DIR_CW, left);
    } else {
        nezha_write(LEFT_PORT, DIR_CCW, -left);
    }

    /* right wheel -- fwd_sign=-1 inverts physical direction */
    if (right >= 0) {
        nezha_write(RIGHT_PORT, DIR_CCW, right);
    } else {
        nezha_write(RIGHT_PORT, DIR_CW, -right);
    }

    return mp_const_none;
}
STATIC MP_DEFINE_CONST_FUN_OBJ_2(robot_drive_obj, robot_drive);

/* robot.stop() -- coast both motors. */
STATIC mp_obj_t robot_stop(void) {
    nezha_write(LEFT_PORT,  DIR_CW, 0);
    nezha_write(RIGHT_PORT, DIR_CW, 0);
    return mp_const_none;
}
STATIC MP_DEFINE_CONST_FUN_OBJ_0(robot_stop_obj, robot_stop);
/* robot.encoders() -> (left_raw, right_raw) */
STATIC mp_obj_t robot_encoders(void) {
    mp_obj_t tuple[2] = {
        mp_obj_new_int_from_uint((uint32_t)nezha_read_encoder(LEFT_PORT)),
        mp_obj_new_int_from_uint((uint32_t)nezha_read_encoder(RIGHT_PORT)),
    };
    return mp_obj_new_tuple(2, tuple);
}
STATIC MP_DEFINE_CONST_FUN_OBJ_0(robot_encoders_obj, robot_encoders);


STATIC const mp_rom_map_elem_t robot_module_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_robot) },
    { MP_ROM_QSTR(MP_QSTR_drive),    MP_ROM_PTR(&robot_drive_obj) },
    { MP_ROM_QSTR(MP_QSTR_stop),     MP_ROM_PTR(&robot_stop_obj) },
    { MP_ROM_QSTR(MP_QSTR_encoders), MP_ROM_PTR(&robot_encoders_obj) },
};
STATIC MP_DEFINE_CONST_DICT(robot_module_globals, robot_module_globals_table);

const mp_obj_module_t robot_module = {
    .base    = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&robot_module_globals,
};

