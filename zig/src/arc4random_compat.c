// Zig 0.16's std.Io may emit an arc4random_buf call for glibc targets even
// when the requested compatibility floor predates glibc 2.36. Keep Linux
// wheels self-contained by providing the equivalent operation via getrandom,
// which has been available since glibc 2.25.
#define _GNU_SOURCE

#include <errno.h>
#include <stddef.h>
#include <stdlib.h>
#include <sys/random.h>

__attribute__((visibility("hidden"))) void arc4random_buf(void *buffer, size_t length) {
    unsigned char *cursor = buffer;

    while (length > 0) {
        const ssize_t count = getrandom(cursor, length, 0);
        if (count > 0) {
            cursor += (size_t)count;
            length -= (size_t)count;
            continue;
        }
        if (count < 0 && errno == EINTR) {
            continue;
        }
        abort();
    }
}
