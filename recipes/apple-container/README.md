# TurboAPI on Apple container

This recipe builds and runs TurboAPI in a Linux arm64 VM on Apple silicon using
Apple's [`container`](https://github.com/apple/container) CLI. It does more than check
that the package imports: the build installs a wheel into a clean Python 3.14t
environment, rejects simulation mode, starts the Zig HTTP server, publishes its
port to macOS, and makes a real request from the host.

## Requirements

- An Apple silicon Mac
- The `container` CLI with its system running (`container system start`); tested
  with `container` 0.11.0
- `curl` and `python3` on the host

Run the complete smoke test from the repository root:

```bash
./recipes/apple-container/smoke.sh
```

A passing run proves all of the following:

- `container` launched a Linux arm64 guest/image without requesting Rosetta;
- Python is pinned CPython 3.14.6 free-threaded (`Py_GIL_DISABLED=1`);
- `turbonet.cpython-314t-aarch64-linux-gnu.so` was installed from the wheel;
- TurboAPI selected the Zig native backend instead of simulation mode; and
- the host can reach a TurboAPI route through the published port.

The image is intentionally built from an allowlisted subset of the checked-out
source so a pull request can be validated before its wheel is published. Its
base image is pinned by digest, and Python, Zig, build tools, and `dhi` are
pinned. Release wheels use the same native runtime checks in
`.github/workflows/build-and-release.yml` after `auditwheel` repairs the Linux
aarch64 artifact.

This is a development smoke image, not a production deployment image.

## DNS workaround

Some Apple container environments can reach IP addresses but cannot resolve
package hosts such as PyPI. The script uses the VM's default resolver normally.
If resolution fails, opt into a resolver available on your network:

```bash
TURBOAPI_CONTAINER_DNS=8.8.8.8 ./recipes/apple-container/smoke.sh
# Or use another resolver:
TURBOAPI_CONTAINER_DNS=1.1.1.1 ./recipes/apple-container/smoke.sh
```

If port 18080 is occupied, choose another loopback port:

```bash
TURBOAPI_SMOKE_PORT=28080 ./recipes/apple-container/smoke.sh
```

The equivalent manual commands below include the optional DNS workaround:

```bash
container build \
  --platform linux/arm64 \
  --dns 8.8.8.8 \
  --file recipes/apple-container/Containerfile \
  --tag turboapi-apple-smoke:local \
  .

container run \
  --rm \
  --detach \
  --name turboapi-apple-smoke \
  --platform linux/arm64 \
  --publish 127.0.0.1:18080:8080 \
  turboapi-apple-smoke:local

curl http://127.0.0.1:18080/__turboapi_native_smoke__
container logs turboapi-apple-smoke
container stop turboapi-apple-smoke
```

If the running application itself needs DNS, add `--dns 8.8.8.8` to
`container run` as well.
