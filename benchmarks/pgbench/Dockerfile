# MagicStack pgbench + TurboAPI pg.zig runner
# Stage 1: Build Python 3.14t + TurboAPI
FROM python:3.14-bookworm AS turbo-builder

RUN ARCH=$(dpkg --print-architecture) \
    && if [ "$ARCH" = "arm64" ]; then ZIG_ARCH=aarch64; else ZIG_ARCH=x86_64; fi \
    && curl -fSL "https://ziglang.org/download/0.15.2/zig-${ZIG_ARCH}-linux-0.15.2.tar.xz" \
       | tar -xJ -C /opt \
    && ln -s /opt/zig-${ZIG_ARCH}-linux-0.15.2/zig /usr/local/bin/zig

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libssl-dev zlib1g-dev libbz2-dev libreadline-dev \
        libsqlite3-dev libncurses5-dev libffi-dev liblzma-dev \
    && PYVER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')") \
    && curl -fSL "https://www.python.org/ftp/python/${PYVER}/Python-${PYVER}.tgz" | tar xz -C /tmp \
    && cd /tmp/Python-${PYVER} \
    && ./configure --prefix=/opt/python3.14t --disable-gil --enable-shared --with-ensurepip=install \
       LDFLAGS="-Wl,-rpath,/opt/python3.14t/lib" 2>&1 | tail -3 \
    && make -j$(nproc) 2>&1 | tail -3 \
    && make install 2>&1 | tail -3 \
    && rm -rf /tmp/Python-*

ENV PATH="/opt/python3.14t/bin:$PATH"

WORKDIR /turboapi
COPY . .
RUN python3 zig/build_turbonet.py --install --release 2>&1 | tail -3
RUN pip3 install --no-cache-dir -e . && pip3 install --no-cache-dir numpy aiohttp

# Stage 2: pgbench + turboapi combined
FROM python:3.11-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libssl-dev libpq-dev git \
    && rm -rf /var/lib/apt/lists/*

# Clone MagicStack pgbench
RUN git clone --depth 1 https://github.com/MagicStack/pgbench.git /pgbench

# pgbench venv (Python 3.11 for asyncpg/psycopg3 compat)
WORKDIR /pgbench/_python
RUN python3 -m venv venv \
    && . venv/bin/activate \
    && pip install --no-cache-dir \
       numpy asyncpg aiopg psycopg2-binary "psycopg[binary]" "uvloop<0.20" py-postgresql distro

# Copy Python 3.14t + TurboAPI from builder
COPY --from=turbo-builder /opt/python3.14t /opt/python3.14t
COPY --from=turbo-builder /turboapi /turboapi

# Copy runner and entrypoint
COPY benchmarks/pgbench/pgbench_zig /pgbench/pgbench_zig
COPY benchmarks/pgbench/run.sh /pgbench/run.sh
RUN chmod +x /pgbench/pgbench_zig /pgbench/run.sh

WORKDIR /pgbench
CMD ["/pgbench/run.sh"]
