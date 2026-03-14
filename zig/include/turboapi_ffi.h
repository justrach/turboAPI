#ifndef TURBOAPI_FFI_H
#define TURBOAPI_FFI_H

#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ── Request passed to native handlers ── */
typedef struct {
    const char *method;       /* "GET", "POST", etc. */
    size_t method_len;
    const char *path;         /* "/users/42" */
    size_t path_len;
    const char *query_string; /* "q=test&limit=10" */
    size_t query_len;
    const char *body;         /* raw request body */
    size_t body_len;
    /* Headers as parallel arrays */
    const char **header_names;
    const size_t *header_name_lens;
    const char **header_values;
    const size_t *header_value_lens;
    size_t header_count;
    /* Path params as parallel arrays */
    const char **param_names;
    const size_t *param_name_lens;
    const char **param_values;
    const size_t *param_value_lens;
    size_t param_count;
} turboapi_request_t;

/* ── Response returned by native handlers ── */
typedef struct {
    uint16_t status_code;     /* 200, 404, etc. */
    const char *content_type; /* "application/json" */
    size_t content_type_len;
    const char *body;         /* response body - must be heap allocated */
    size_t body_len;
} turboapi_response_t;

/*
 * Native handler function signature.
 * The handler receives a request and must return a response.
 * The response body must be allocated with malloc() — TurboAPI will free() it.
 * The content_type can be a static string (not freed).
 *
 * Example:
 *   turboapi_response_t handle_health(const turboapi_request_t *req) {
 *       const char *body = strdup("{\"status\": \"ok\"}");
 *       return (turboapi_response_t){
 *           .status_code = 200,
 *           .content_type = "application/json",
 *           .content_type_len = 16,
 *           .body = body,
 *           .body_len = strlen(body),
 *       };
 *   }
 */
typedef turboapi_response_t (*turboapi_handler_fn)(const turboapi_request_t *request);

/* Optional: called once when the library is loaded. Return 0 on success. */
typedef int (*turboapi_init_fn)(void);

/* Optional: called on server shutdown for cleanup. */
typedef void (*turboapi_cleanup_fn)(void);

#ifdef __cplusplus
}
#endif

#endif /* TURBOAPI_FFI_H */
