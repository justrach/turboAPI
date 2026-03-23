/* GIL release shim for Zig.
 * PyThreadState is opaque in Zig's cimport, so we wrap
 * PyEval_SaveThread/RestoreThread to return void* instead.
 */
#define PY_SSIZE_T_CLEAN
#include <Python.h>

void* py_gil_save(void) {
    return (void*)PyEval_SaveThread();
}

void py_gil_restore(void* tstate) {
    PyEval_RestoreThread((PyThreadState*)tstate);
}
