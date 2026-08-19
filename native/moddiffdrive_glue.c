/*
 * moddiffdrive_glue.c -- MicroPython module registration for `diffdrive`
 * and `robotio`, mirroring reference/modrobot/modrobot_glue.c's proven
 * two-file pattern (C++ logic in moddiffdrive.cpp, plain-C MP module
 * table here). Two modules, one glue file: robotio.i2c_xfer() shares the
 * same underlying I2cBroker instance moddiffdrive.cpp's kernel leaves
 * use (native/i2c_broker.h) -- see moddiffdrive.cpp's own file header.
 */
#include "py/obj.h"
#include "py/runtime.h"

extern mp_obj_t diffdrive_configure_fn(size_t n_args, const mp_obj_t *pos_args,
                                        mp_map_t *kw_args);
extern mp_obj_t diffdrive_begin_fn(void);
extern mp_obj_t diffdrive_start_fn(void);
extern mp_obj_t diffdrive_drive_fn(mp_obj_t velocityObj, mp_obj_t twistObj,
                                    mp_obj_t leaseObj);
extern mp_obj_t diffdrive_driveDuty_fn(mp_obj_t dutyLeftObj, mp_obj_t dutyRightObj,
                                        mp_obj_t leaseObj);
extern mp_obj_t diffdrive_neutral_fn(void);
extern mp_obj_t diffdrive_estop_fn(void);
extern mp_obj_t diffdrive_output_fn(void);
extern mp_obj_t diffdrive_lastError_fn(void);
extern mp_obj_t diffdrive_cycleOverrunCount_fn(void);

extern mp_obj_t robotio_i2c_xfer_fn(size_t n_args, const mp_obj_t *pos_args,
                                     mp_map_t *kw_args);

STATIC MP_DEFINE_CONST_FUN_OBJ_KW(diffdrive_configure_obj, 0, diffdrive_configure_fn);
STATIC MP_DEFINE_CONST_FUN_OBJ_0(diffdrive_begin_obj, diffdrive_begin_fn);
STATIC MP_DEFINE_CONST_FUN_OBJ_0(diffdrive_start_obj, diffdrive_start_fn);
STATIC MP_DEFINE_CONST_FUN_OBJ_3(diffdrive_drive_obj, diffdrive_drive_fn);
STATIC MP_DEFINE_CONST_FUN_OBJ_3(diffdrive_driveDuty_obj, diffdrive_driveDuty_fn);
STATIC MP_DEFINE_CONST_FUN_OBJ_0(diffdrive_neutral_obj, diffdrive_neutral_fn);
STATIC MP_DEFINE_CONST_FUN_OBJ_0(diffdrive_estop_obj, diffdrive_estop_fn);
STATIC MP_DEFINE_CONST_FUN_OBJ_0(diffdrive_output_obj, diffdrive_output_fn);
STATIC MP_DEFINE_CONST_FUN_OBJ_0(diffdrive_lastError_obj, diffdrive_lastError_fn);
STATIC MP_DEFINE_CONST_FUN_OBJ_0(diffdrive_cycleOverrunCount_obj,
                                  diffdrive_cycleOverrunCount_fn);

STATIC const mp_rom_map_elem_t diffdrive_module_globals_table[] = {
    {MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_diffdrive)},
    {MP_ROM_QSTR(MP_QSTR_configure), MP_ROM_PTR(&diffdrive_configure_obj)},
    {MP_ROM_QSTR(MP_QSTR_begin), MP_ROM_PTR(&diffdrive_begin_obj)},
    {MP_ROM_QSTR(MP_QSTR_start), MP_ROM_PTR(&diffdrive_start_obj)},
    {MP_ROM_QSTR(MP_QSTR_drive), MP_ROM_PTR(&diffdrive_drive_obj)},
    {MP_ROM_QSTR(MP_QSTR_driveDuty), MP_ROM_PTR(&diffdrive_driveDuty_obj)},
    {MP_ROM_QSTR(MP_QSTR_neutral), MP_ROM_PTR(&diffdrive_neutral_obj)},
    {MP_ROM_QSTR(MP_QSTR_estop), MP_ROM_PTR(&diffdrive_estop_obj)},
    {MP_ROM_QSTR(MP_QSTR_output), MP_ROM_PTR(&diffdrive_output_obj)},
    {MP_ROM_QSTR(MP_QSTR_lastError), MP_ROM_PTR(&diffdrive_lastError_obj)},
    {MP_ROM_QSTR(MP_QSTR_cycleOverrunCount),
     MP_ROM_PTR(&diffdrive_cycleOverrunCount_obj)},
};
STATIC MP_DEFINE_CONST_DICT(diffdrive_module_globals, diffdrive_module_globals_table);

const mp_obj_module_t diffdrive_module = {
    .base = {&mp_type_module},
    .globals = (mp_obj_dict_t *)&diffdrive_module_globals,
};

STATIC MP_DEFINE_CONST_FUN_OBJ_KW(robotio_i2c_xfer_obj, 0, robotio_i2c_xfer_fn);

STATIC const mp_rom_map_elem_t robotio_module_globals_table[] = {
    {MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_robotio)},
    {MP_ROM_QSTR(MP_QSTR_i2c_xfer), MP_ROM_PTR(&robotio_i2c_xfer_obj)},
};
STATIC MP_DEFINE_CONST_DICT(robotio_module_globals, robotio_module_globals_table);

const mp_obj_module_t robotio_module = {
    .base = {&mp_type_module},
    .globals = (mp_obj_dict_t *)&robotio_module_globals,
};
