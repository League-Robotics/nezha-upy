/*
 * modrobot_glue.c -- MicroPython module registration for the robot module.
 */
#include "py/runtime.h"
#include "py/obj.h"

extern mp_obj_t robot_move_fn(size_t n_args, const mp_obj_t *args);
extern mp_obj_t robot_turn_fn(size_t n_args, const mp_obj_t *args);
extern mp_obj_t robot_go_to_fn(size_t n_args, const mp_obj_t *args);
extern mp_obj_t robot_move_wheels_fn(mp_obj_t leftObj, mp_obj_t rightObj, mp_obj_t msObj);
extern mp_obj_t robot_set_wheels_fn(mp_obj_t leftObj, mp_obj_t rightObj);
extern mp_obj_t robot_drive_wheels_fn(mp_obj_t leftObj, mp_obj_t rightObj);
extern mp_obj_t robot_stop_fn(void);
extern mp_obj_t robot_encoders_fn(void);
extern mp_obj_t robot_otos_fn(void);
extern mp_obj_t robot_line_fn(void);
extern mp_obj_t robot_color_fn(void);
extern mp_obj_t robot_servo_fn(mp_obj_t portObj, mp_obj_t angleObj);
extern mp_obj_t robot_enter_v5_fn(void);
extern mp_obj_t robot_wifi_status_fn(void);
extern mp_obj_t robot_ping_fn(void);
extern mp_obj_t robot_tlm_fn(void);

STATIC MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(robot_move_obj, 4, 4, robot_move_fn);
STATIC MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(robot_turn_obj, 3, 3, robot_turn_fn);
STATIC MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(robot_go_to_obj, 6, 6, robot_go_to_fn);
STATIC MP_DEFINE_CONST_FUN_OBJ_3(robot_move_wheels_obj, robot_move_wheels_fn);
STATIC MP_DEFINE_CONST_FUN_OBJ_2(robot_set_wheels_obj, robot_set_wheels_fn);
STATIC MP_DEFINE_CONST_FUN_OBJ_2(robot_drive_obj, robot_drive_wheels_fn);
STATIC MP_DEFINE_CONST_FUN_OBJ_0(robot_stop_obj, robot_stop_fn);
STATIC MP_DEFINE_CONST_FUN_OBJ_0(robot_encoders_obj, robot_encoders_fn);
STATIC MP_DEFINE_CONST_FUN_OBJ_0(robot_otos_obj, robot_otos_fn);
STATIC MP_DEFINE_CONST_FUN_OBJ_0(robot_line_obj, robot_line_fn);
STATIC MP_DEFINE_CONST_FUN_OBJ_0(robot_color_obj, robot_color_fn);
STATIC MP_DEFINE_CONST_FUN_OBJ_2(robot_servo_obj, robot_servo_fn);
STATIC MP_DEFINE_CONST_FUN_OBJ_0(robot_enter_v5_obj, robot_enter_v5_fn);
STATIC MP_DEFINE_CONST_FUN_OBJ_0(robot_wifi_status_obj, robot_wifi_status_fn);
STATIC MP_DEFINE_CONST_FUN_OBJ_0(robot_ping_obj, robot_ping_fn);
STATIC MP_DEFINE_CONST_FUN_OBJ_0(robot_tlm_obj, robot_tlm_fn);

STATIC const mp_rom_map_elem_t robot_module_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__),      MP_ROM_QSTR(MP_QSTR_robot) },
    { MP_ROM_QSTR(MP_QSTR_move),          MP_ROM_PTR(&robot_move_obj) },
    { MP_ROM_QSTR(MP_QSTR_turn),          MP_ROM_PTR(&robot_turn_obj) },
    { MP_ROM_QSTR(MP_QSTR_go_to),         MP_ROM_PTR(&robot_go_to_obj) },
    { MP_ROM_QSTR(MP_QSTR_drive),         MP_ROM_PTR(&robot_drive_obj) },
    { MP_ROM_QSTR(MP_QSTR_move_wheels),   MP_ROM_PTR(&robot_move_wheels_obj) },
    { MP_ROM_QSTR(MP_QSTR_set_wheels),    MP_ROM_PTR(&robot_set_wheels_obj) },
    { MP_ROM_QSTR(MP_QSTR_stop),          MP_ROM_PTR(&robot_stop_obj) },
    { MP_ROM_QSTR(MP_QSTR_encoders),      MP_ROM_PTR(&robot_encoders_obj) },
    { MP_ROM_QSTR(MP_QSTR_otos),          MP_ROM_PTR(&robot_otos_obj) },
    { MP_ROM_QSTR(MP_QSTR_line),          MP_ROM_PTR(&robot_line_obj) },
    { MP_ROM_QSTR(MP_QSTR_color),         MP_ROM_PTR(&robot_color_obj) },
    { MP_ROM_QSTR(MP_QSTR_servo),         MP_ROM_PTR(&robot_servo_obj) },
    { MP_ROM_QSTR(MP_QSTR_enter_v5),      MP_ROM_PTR(&robot_enter_v5_obj) },
    { MP_ROM_QSTR(MP_QSTR_wifi_status),   MP_ROM_PTR(&robot_wifi_status_obj) },
    { MP_ROM_QSTR(MP_QSTR_ping),          MP_ROM_PTR(&robot_ping_obj) },
    { MP_ROM_QSTR(MP_QSTR_tlm),           MP_ROM_PTR(&robot_tlm_obj) },
};
STATIC MP_DEFINE_CONST_DICT(robot_module_globals, robot_module_globals_table);

const mp_obj_module_t robot_module = {
    .base    = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&robot_module_globals,
};
