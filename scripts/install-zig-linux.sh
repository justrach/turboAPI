#!/bin/sh
set -eu

ZIG_VERSION=0.17.0-dev.1862+40ebd8162
ZIG_SHA256_AARCH64=f2bda379a3fa49f8450d17d80ca6280549bb160cf4d1aff81f54c64ac2d474be

arch=$(uname -m)
if [ "$arch" != "aarch64" ]; then
    echo "Expected native Linux aarch64, got: $arch" >&2
    exit 1
fi

archive="zig-${arch}-linux-${ZIG_VERSION}.tar.xz"
url="https://ziglang.org/builds/${archive}"
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
