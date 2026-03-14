/* Shim for Python 3.14t free-threaded build.
   Zig's @cImport translate-C cannot inline static-inline atomic functions
   from pyatomic_gcc.h. We provide the missing symbol directly using
   C11 stdatomic, matching what pyatomic_gcc.h does. */

#include <stdint.h>
#include <stdatomic.h>

uint64_t _Py_atomic_load_uint64_relaxed(const uint64_t *obj) {
    return atomic_load_explicit((_Atomic(uint64_t) *)obj, memory_order_relaxed);
}
