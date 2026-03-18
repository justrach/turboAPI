# Security Policy

## Threat Model

TurboAPI sits at the boundary between the internet and your Python application. The security surface has three distinct layers:

```
Internet → [Zig HTTP core] → [dhi validator] → [Python handler]
```

### Layer 1: Zig HTTP Core (`server.zig`)

What it accepts:
- TCP connections on a configurable port
- HTTP/1.1 requests with headers up to 8KB
- Request bodies up to **16MB** (hardcoded; configurable max body size is on the roadmap — see [#37](https://github.com/justrach/turboAPI/issues/37))

What it rejects at the TCP/parse level:
- Requests with `Content-Length` exceeding the 16MB cap (returns 413)
- Malformed HTTP/1.1 request lines (returns 400)
- Headers that overflow the 8KB header buffer (returns 431)

**Known gaps:**
- No slow-loris protection (no per-connection read timeout yet)
- No max header count limit (high header count won't crash, but isn't capped)
- CRLF injection in header values is not explicitly sanitized — rely on your reverse proxy (nginx/Caddy) for this in production

### Layer 2: dhi Validator (`dhi_validator.zig`)

For `model_sync` routes (handlers that accept a `dhi.BaseModel`), the request body is parsed and validated **before** the GIL is acquired:

- JSON schema validation (field types, required fields, `min_length`, `max_length`, `gt`, `lt`, `ge`, `le`)
- Nested object and array validation
- Invalid requests return `422 Unprocessable Entity` — **Python is never called**

This means a flood of malformed POST requests to model-validated endpoints cannot exhaust the Python thread pool — the Zig layer rejects them with negligible CPU cost.

**Depth bombs:** Deeply nested JSON (e.g., `{"a":{"a":{"a":...}}}`) are not yet depth-limited in the parser. A 1000-level nested JSON will parse slowly. If your endpoint accepts arbitrary JSON, add a body size limit in your handler or at the proxy layer.

### Layer 3: Python Handlers

Standard Python security practices apply. TurboAPI does not add injection risks beyond what your handler code introduces.

---

## Security Testing Status

| Component | Fuzz tested | Notes |
|-----------|-------------|-------|
| HTTP parser (header parsing) | ❌ Not yet | Planned — see [#37](https://github.com/justrach/turboAPI/issues/37) |
| HTTP parser (URL/path decoding) | ❌ Not yet | Percent-encoding edge cases, null bytes |
| JSON body parser | ❌ Not yet | Depth bombs, huge strings, invalid UTF-8 |
| dhi schema validator | ❌ Not yet | Adversarial schema inputs |
| Router (radix trie) | ❌ Not yet | Path traversal, very long paths |

**Fuzz testing is a known gap.** TurboAPI is alpha software. Do not expose it directly to the internet without a hardened reverse proxy (nginx, Caddy, Cloudflare) in front of it.

---

## Deployment Recommendations

For any production or semi-production use:

1. **Put a reverse proxy in front** — nginx or Caddy handles slow-loris, TLS termination, and request header sanitization. TurboAPI should bind to `127.0.0.1`, not `0.0.0.0`, when behind a proxy.

2. **Set body size limits at the proxy layer** — until TurboAPI has a configurable `max_body_size`, use `client_max_body_size 1m;` (nginx) or `max_request_body_size 1mb` (Caddy).

3. **Use HTTPS via the proxy** — TurboAPI does not yet support TLS natively (HTTP/2 + TLS is in progress).

4. **Namespace your routes** — use `APIRouter` with a prefix so internal routes (health checks, metrics) are not accidentally exposed.

5. **Rate-limit at the proxy or CDN layer** — TurboAPI has no built-in rate limiting.

---

## Reporting a Vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.

Report security issues privately via GitHub's [Security Advisory](https://github.com/justrach/turboAPI/security/advisories/new) feature, or email the maintainer directly (see the GitHub profile).

Include:
- A description of the vulnerability
- Steps to reproduce (minimal repro preferred)
- The version of TurboAPI and Python you were using
- The impact you believe this has

We aim to acknowledge reports within **48 hours** and provide a fix or mitigation within **14 days** for critical issues.

---

## Mitigations Already In Place

| Attack | Mitigation |
|--------|------------|
| Invalid JSON flooding `model_sync` endpoints | Rejected in Zig before GIL — Python handler never called |
| Schema violation flooding `model_sync` endpoints | dhi validator rejects with 422, no Python cost |
| Large body DoS | 16MB hardcoded cap; returns 413 |
| Oversized headers | 8KB header buffer; returns 431 |
| Path traversal in router | Radix trie matches literal path segments; no filesystem access |

---

## Alpha Status Notice

TurboAPI is **alpha software**. The security posture described here reflects what has been implemented, not what has been audited. Treat it accordingly:

- Do not use it as the sole security boundary
- Do not store sensitive data in handler memory without understanding the threading model
- Free-threaded Python 3.14t is itself in a relatively early maturity stage — `threading.local()` and some C extensions may not be thread-safe

The fastest path to a secure deployment is: **reverse proxy → TurboAPI → your handler**.
