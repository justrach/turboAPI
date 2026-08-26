# TurboAPI — optimized Python 3.14t + Zig 0.17-dev native backend
FROM python:3.14.7-bookworm AS builder

# Pin and verify the interpreter source. The root image is used by latency-
# sensitive deployments, so silently following a mutable Python tag is unsafe.
ARG PYTHON_VERSION=3.14.7
ARG PYTHON_SOURCE_SHA256=62859805f6fdf25e2bcbf3fa3217801e1996887ca33e6a2af80674bdfa2dbe07

# Keep this exact nightly aligned with zig/build.zig.zon and CI.
ARG ZIG_VERSION=0.17.0-dev.1862+40ebd8162
RUN ARCH=$(dpkg --print-architecture) \
    && case "$ARCH" in \
        arm64) ZIG_ARCH=aarch64; ZIG_SHA256=f2bda379a3fa49f8450d17d80ca6280549bb160cf4d1aff81f54c64ac2d474be ;; \
        amd64) ZIG_ARCH=x86_64; ZIG_SHA256=8e76bc57585fc9c257c6c3053a522501f6a6e7baae801490d269ec036c75b58d ;; \
        *) echo "Unsupported architecture: $ARCH" >&2; exit 1 ;; \
    esac \
    && ARCHIVE="zig-${ZIG_ARCH}-linux-${ZIG_VERSION}.tar.xz" \
    && curl -fSL "https://ziglang.org/builds/${ARCHIVE}" -o "/tmp/${ARCHIVE}" \
    && echo "${ZIG_SHA256}  /tmp/${ARCHIVE}" | sha256sum --check - \
    && tar -xJf "/tmp/${ARCHIVE}" -C /opt \
    && ln -s "/opt/zig-${ZIG_ARCH}-linux-${ZIG_VERSION}/zig" /usr/local/bin/zig \
    && test "$(zig version)" = "$ZIG_VERSION" \
    && rm "/tmp/${ARCHIVE}"

# Build the free-threaded interpreter with the same optimization guarantees as
# the known-good uv/astral CPython runtime. BOLT is deliberately not required:
# Debian's native GCC toolchain supports reproducible PGO + full LTO on both
# amd64 and arm64, while BOLT would require a separate LLVM profile pipeline.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libssl-dev zlib1g-dev libbz2-dev libreadline-dev \
        libsqlite3-dev libncurses5-dev libffi-dev liblzma-dev \
    && PYTHON_ARCHIVE="Python-${PYTHON_VERSION}.tgz" \
    && curl -fSL \
       "https://www.python.org/ftp/python/${PYTHON_VERSION}/${PYTHON_ARCHIVE}" \
       -o "/tmp/${PYTHON_ARCHIVE}" \
    && echo "${PYTHON_SOURCE_SHA256}  /tmp/${PYTHON_ARCHIVE}" | sha256sum --check - \
    && tar -xzf "/tmp/${PYTHON_ARCHIVE}" -C /tmp \
    && cd "/tmp/Python-${PYTHON_VERSION}" \
    && ./configure \
       --prefix=/opt/python3.14t \
       --disable-gil \
       --enable-shared \
       --enable-optimizations \
       --with-lto=full \
       --with-mimalloc \
       --with-ensurepip=install \
       LDFLAGS="-Wl,-rpath,/opt/python3.14t/lib" \
    && make -j"$(nproc)" \
    && make install \
    && /opt/python3.14t/bin/python3 -c \
       "import sys; assert sys.version_info[:3] == (3, 14, 7); assert not sys._is_gil_enabled()" \
    && rm -rf /tmp/Python-*

ENV PATH="/opt/python3.14t/bin:$PATH"

WORKDIR /app
COPY . .

# Build the Zig native backend (dhi fetched automatically via build.zig.zon)
RUN python3 zig/build_turbonet.py --install --release

# ── Runtime stage ──
FROM debian:bookworm-slim

ARG PYTHON_VERSION=3.14.7

# Copy free-threaded Python + turboapi
COPY --from=builder /opt/python3.14t /opt/python3.14t
ENV PATH="/opt/python3.14t/bin:$PATH" \
    PYTHON_VERSION="${PYTHON_VERSION}" \
    PYTHON_BUILD_FEATURES="free-threaded,pgo,lto,mimalloc"

# Runtime deps for Python
RUN apt-get update && apt-get install -y --no-install-recommends \
        libssl3 zlib1g libbz2-1.0 libreadline8 libsqlite3-0 \
        libncurses6 libffi8 liblzma5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /app /app

# Install turboapi + deps
RUN pip3 install --no-cache-dir -e . \
    && python3 scripts/verify_optimized_runtime.py \
       --expect-version "${PYTHON_VERSION}" \
       --require-native

EXPOSE 8000
CMD ["python3", "test_docker_app.py"]
