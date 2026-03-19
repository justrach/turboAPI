# TurboAPI — Python 3.14 free-threaded + Zig 0.15 native backend
FROM python:3.14-bookworm AS builder

# Install Zig 0.15.2
RUN ARCH=$(dpkg --print-architecture) \
    && if [ "$ARCH" = "arm64" ]; then ZIG_ARCH=aarch64; else ZIG_ARCH=x86_64; fi \
    && curl -fSL "https://ziglang.org/download/0.15.2/zig-${ZIG_ARCH}-linux-0.15.2.tar.xz" \
       | tar -xJ -C /opt \
    && ln -s /opt/zig-${ZIG_ARCH}-linux-0.15.2/zig /usr/local/bin/zig

# Build Python 3.14 free-threaded from source
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libssl-dev zlib1g-dev libbz2-dev libreadline-dev \
        libsqlite3-dev libncurses5-dev libffi-dev liblzma-dev \
    && PYVER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')") \
    && curl -fSL "https://www.python.org/ftp/python/${PYVER}/Python-${PYVER}.tgz" | tar xz -C /tmp \
    && cd /tmp/Python-${PYVER} \
    && ./configure --prefix=/opt/python3.14t --disable-gil --enable-shared --with-ensurepip=install \
       LDFLAGS="-Wl,-rpath,/opt/python3.14t/lib" 2>&1 | tail -5 \
    && make -j$(nproc) 2>&1 | tail -3 \
    && make install 2>&1 | tail -3 \
    && /opt/python3.14t/bin/python3 -c "import sys; assert not sys._is_gil_enabled(); print('Free-threaded OK')" \
    && rm -rf /tmp/Python-*

ENV PATH="/opt/python3.14t/bin:$PATH"

WORKDIR /app
COPY . .

# Build the Zig native backend (dhi fetched automatically via build.zig.zon)
RUN python3 zig/build_turbonet.py --install --release

# ── Runtime stage ──
FROM debian:bookworm-slim

# Copy free-threaded Python + turboapi
COPY --from=builder /opt/python3.14t /opt/python3.14t
ENV PATH="/opt/python3.14t/bin:$PATH"

# Runtime deps for Python
RUN apt-get update && apt-get install -y --no-install-recommends \
        libssl3 zlib1g libbz2-1.0 libreadline8 libsqlite3-0 \
        libncurses6 libffi8 liblzma5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /app /app

# Install turboapi + deps
RUN pip3 install --no-cache-dir -e .

EXPOSE 8000
CMD ["python3", "test_docker_app.py"]
