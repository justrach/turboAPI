# turboAPI demo image — Python 3.14t free-threaded + Zig 0.16 backend
#
# Built and pushed automatically by .github/workflows/docker-image.yml on every
# `v*` tag. Pull from `ghcr.io/justrach/turboapi:<tag>` or `:latest`.
#
# Build context: the repo root (so `COPY . .` picks up the tagged source).

FROM python:3.14-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates git build-essential xz-utils && \
    rm -rf /var/lib/apt/lists/*

# Zig 0.16.0 — required by the telemetry module on main / v1.0.29+
RUN ARCH=$(uname -m) && \
    curl -fsSL "https://ziglang.org/download/0.16.0/zig-${ARCH}-linux-0.16.0.tar.xz" \
        | tar -xJ -C /opt && \
    mv "/opt/zig-${ARCH}-linux-0.16.0" /opt/zig
ENV PATH="/opt/zig:$PATH"

# uv + free-threaded Python 3.14t (precompiled, no source build)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"
RUN uv python install 3.14t && uv venv --python 3.14t /venv
ENV PATH="/venv/bin:$PATH" VIRTUAL_ENV="/venv"

WORKDIR /turboapi
COPY . .

RUN uv pip install dhi && uv pip install -e ./python

RUN python zig/build_turbonet.py && \
    SOABI=$(python -c "import sysconfig; print(sysconfig.get_config_var('SOABI'))") && \
    cp zig/zig-out/lib/libturbonet.so "python/turboapi/turbonet.${SOABI}.so"

ENV PORT=8080
EXPOSE 8080
CMD ["/venv/bin/python", "/turboapi/docker/app.py"]
