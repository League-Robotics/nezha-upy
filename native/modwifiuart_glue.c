/*
 * modwifiuart_glue.c -- MicroPython module registration for `wifiuart`,
 * mirroring moddiffdrive_glue.c's own established two-file pattern
 * (C++ logic in modwifiuart.cpp, plain-C MP module table here).
 */
#include "py/obj.h"
#include "py/runtime.h"

extern mp_obj_t wifiuart_init_fn(size_t n_args, const mp_obj_t *pos_args,
                                  mp_map_t *kw_args);
extern mp_obj_t wifiuart_write_fn(mp_obj_t dataObj);
extern mp_obj_t wifiuart_any_fn(void);
extern mp_obj_t wifiuart_read_fn(mp_obj_t nObj);
extern mp_obj_t wifiuart_repl_active_fn(mp_obj_t flagObj);
extern mp_obj_t wifiuart_stdin_push_fn(mp_obj_t dataObj);
extern mp_obj_t wifiuart_stdout_pull_fn(mp_obj_t nObj);

STATIC MP_DEFINE_CONST_FUN_OBJ_KW(wifiuart_init_obj, 0, wifiuart_init_fn);
STATIC MP_DEFINE_CONST_FUN_OBJ_1(wifiuart_write_obj, wifiuart_write_fn);
STATIC MP_DEFINE_CONST_FUN_OBJ_0(wifiuart_any_obj, wifiuart_any_fn);
STATIC MP_DEFINE_CONST_FUN_OBJ_1(wifiuart_read_obj, wifiuart_read_fn);
STATIC MP_DEFINE_CONST_FUN_OBJ_1(wifiuart_repl_active_obj, wifiuart_repl_active_fn);
STATIC MP_DEFINE_CONST_FUN_OBJ_1(wifiuart_stdin_push_obj, wifiuart_stdin_push_fn);
STATIC MP_DEFINE_CONST_FUN_OBJ_1(wifiuart_stdout_pull_obj, wifiuart_stdout_pull_fn);

STATIC const mp_rom_map_elem_t wifiuart_module_globals_table[] = {
    {MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_wifiuart)},
    {MP_ROM_QSTR(MP_QSTR_init), MP_ROM_PTR(&wifiuart_init_obj)},
    {MP_ROM_QSTR(MP_QSTR_write), MP_ROM_PTR(&wifiuart_write_obj)},
    {MP_ROM_QSTR(MP_QSTR_any), MP_ROM_PTR(&wifiuart_any_obj)},
    {MP_ROM_QSTR(MP_QSTR_read), MP_ROM_PTR(&wifiuart_read_obj)},
    {MP_ROM_QSTR(MP_QSTR_repl_active), MP_ROM_PTR(&wifiuart_repl_active_obj)},
    {MP_ROM_QSTR(MP_QSTR_stdin_push), MP_ROM_PTR(&wifiuart_stdin_push_obj)},
    {MP_ROM_QSTR(MP_QSTR_stdout_pull), MP_ROM_PTR(&wifiuart_stdout_pull_obj)},
};
STATIC MP_DEFINE_CONST_DICT(wifiuart_module_globals, wifiuart_module_globals_table);

const mp_obj_module_t wifiuart_module = {
    .base = {&mp_type_module},
    .globals = (mp_obj_dict_t *)&wifiuart_module_globals,
};
