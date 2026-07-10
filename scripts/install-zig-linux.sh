#!/bin/sh
set -eu

ZIG_VERSION=0.16.0
ZIG_SHA256_AARCH64=ea4b09bfb22ec6f6c6ceac57ab63efb6b46e17ab08d21f69f3a48b38e1534f17

arch=$(uname -m)
if [ "$arch" != "aarch64" ]; then
    echo "Expected native Linux aarch64, got: $arch" >&2
    exit 1
fi

archive="zig-${arch}-linux-${ZIG_VERSION}.tar.xz"
url="https://ziglang.org/download/${ZIG_VERSION}/${archive}"
tmp_dir=$(mktemp -d)
trap 'rm -rf "$tmp_dir"' EXIT HUP INT TERM

curl --fail --location --silent --show-error "$url" --output "$tmp_dir/$archive"
printf '%s  %s\n' "$ZIG_SHA256_AARCH64" "$tmp_dir/$archive" | sha256sum --check -

rm -rf /opt/zig
mkdir -p /opt/zig
tar -xJf "$tmp_dir/$archive" --strip-components=1 -C /opt/zig
ln -sf /opt/zig/zig /usr/local/bin/zig

test "$(zig version)" = "$ZIG_VERSION"
echo "Installed Zig $(zig version) for $arch"
