#!/usr/bin/env bash
set -euo pipefail

image=${TURBOAPI_SMOKE_IMAGE:-turboapi-apple-smoke:local}
name="turboapi-apple-smoke-$$"
port=${TURBOAPI_SMOKE_PORT:-18080}
dns=${TURBOAPI_CONTAINER_DNS-}
container_id=

dns_args=()
if [[ -n "$dns" ]]; then
    dns_args=(--dns "$dns")
fi

cleanup() {
    if [[ -n "$container_id" ]]; then
        container stop "$container_id" >/dev/null 2>&1 || true
        container rm "$container_id" >/dev/null 2>&1 || true
    fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

container system status >/dev/null
container build \
    --platform linux/arm64 \
    "${dns_args[@]}" \
    --file recipes/apple-container/Containerfile \
    --tag "$image" \
    .

container_id=$(container run \
    --rm \
    --detach \
    --name "$name" \
    --platform linux/arm64 \
    --publish "127.0.0.1:${port}:8080" \
    "$image")

body=
for _ in {1..60}; do
    if body=$(curl --fail --silent --show-error \
        "http://127.0.0.1:${port}/__turboapi_native_smoke__" 2>/dev/null); then
        break
    fi
    sleep 1
done

if [[ -z "$body" ]]; then
    echo "TurboAPI did not become ready" >&2
    container logs "$container_id" >&2 || true
    exit 1
fi

python3 - "$body" <<'PY'
import json
import sys

actual = json.loads(sys.argv[1])
expected = {
    "ok": True,
    "runtime": "apple-container-linux-arm64-cp314t",
}
assert actual == expected, (actual, expected)
PY

container logs "$container_id"
echo "TurboAPI native Apple container smoke passed: http://127.0.0.1:${port}"
