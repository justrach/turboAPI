# turboAPI demo image — Python 3.14t free-threaded + Zig 0.17-dev backend
#
# Built and pushed automatically by .github/workflows/docker-image.yml on every
# `v*` tag. Pull from `ghcr.io/justrach/turboapi:<tag>` or `:latest`.
#
# Build context: the repo root (so `COPY . .` picks up the tagged source).

FROM python:3.14-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates git build-essential xz-utils && \
    rm -rf /var/lib/apt/lists/*

# Keep this exact nightly aligned with zig/build.zig.zon and CI.
ARG ZIG_VERSION=0.17.0-dev.1862+40ebd8162
RUN ARCH=$(uname -m) && \
    case "$ARCH" in \
        aarch64) ZIG_SHA256=f2bda379a3fa49f8450d17d80ca6280549bb160cf4d1aff81f54c64ac2d474be ;; \
        x86_64) ZIG_SHA256=8e76bc57585fc9c257c6c3053a522501f6a6e7baae801490d269ec036c75b58d ;; \
        *) echo "Unsupported architecture: $ARCH" >&2; exit 1 ;; \
    esac && \
    ARCHIVE="zig-${ARCH}-linux-${ZIG_VERSION}.tar.xz" && \
    curl -fsSL "https://ziglang.org/builds/${ARCHIVE}" -o "/tmp/${ARCHIVE}" && \
    echo "${ZIG_SHA256}  /tmp/${ARCHIVE}" | sha256sum --check - && \
    tar -xJf "/tmp/${ARCHIVE}" -C /opt && \
    mv "/opt/zig-${ARCH}-linux-${ZIG_VERSION}" /opt/zig && \
    rm "/tmp/${ARCHIVE}" && \
    test "$(/opt/zig/zig version)" = "$ZIG_VERSION"
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
