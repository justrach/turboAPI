# Benchmark runner: Python 3.14t + Zig + wrk + asyncpg
FROM python:3.14-bookworm AS builder

# Install Zig
RUN ARCH=$(dpkg --print-architecture) \
    && if [ "$ARCH" = "arm64" ]; then ZIG_ARCH=aarch64; else ZIG_ARCH=x86_64; fi \
    && curl -fSL "https://ziglang.org/download/0.15.2/zig-${ZIG_ARCH}-linux-0.15.2.tar.xz" \
       | tar -xJ -C /opt \
    && ln -s /opt/zig-${ZIG_ARCH}-linux-0.15.2/zig /usr/local/bin/zig

# Install wrk
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libssl-dev \
    && git clone --depth 1 https://github.com/wg/wrk.git /tmp/wrk \
    && cd /tmp/wrk && make -j$(nproc) && cp wrk /usr/local/bin/ \
    && rm -rf /tmp/wrk /var/lib/apt/lists/*

# Build Python 3.14 free-threaded
RUN PYVER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')") \
    && curl -fSL "https://www.python.org/ftp/python/${PYVER}/Python-${PYVER}.tgz" | tar xz -C /tmp \
    && cd /tmp/Python-${PYVER} \
    && ./configure --prefix=/opt/python3.14t --disable-gil --enable-shared --with-ensurepip=install \
       LDFLAGS="-Wl,-rpath,/opt/python3.14t/lib" 2>&1 | tail -3 \
    && make -j$(nproc) 2>&1 | tail -3 \
    && make install 2>&1 | tail -3 \
    && rm -rf /tmp/Python-*

ENV PATH="/opt/python3.14t/bin:$PATH"

WORKDIR /app
COPY . .

# Build Zig backend
RUN python3 zig/build_turbonet.py --install --release

# Install deps
RUN pip3 install --no-cache-dir -e . && pip3 install --no-cache-dir asyncpg requests

COPY benchmarks/postgres/bench.py /app/bench.py
COPY benchmarks/postgres/varying_ids.lua /app/varying_ids.lua

CMD ["python3", "/app/bench.py"]
