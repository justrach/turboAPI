FROM ubuntu:24.04

# Install build dependencies
RUN apt-get update && apt-get install -y \
    wget xz-utils build-essential git \
    && rm -rf /var/lib/apt/lists/*

# Install Zig 0.15.2
RUN wget -q https://ziglang.org/download/0.15.2/zig-linux-x86_64-0.15.2.tar.xz \
    && tar xf zig-linux-x86_64-0.15.2.tar.xz \
    && mv zig-linux-x86_64-0.15.2 /opt/zig \
    && rm zig-linux-x86_64-0.15.2.tar.xz
ENV PATH="/opt/zig:$PATH"

# Install Python 3.14t (free-threaded)
RUN wget -q https://github.com/indygreg/python-build-standalone/releases/download/20250409/cpython-3.14.0a7+freethreaded-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz \
    && tar xf cpython-3.14*.tar.gz \
    && mv python /opt/python3.14t \
    && rm cpython-3.14*.tar.gz
ENV PATH="/opt/python3.14t/bin:$PATH"
ENV PYTHON_GIL=0

WORKDIR /turboapi

# Clone and install turboapi
RUN git clone --depth 1 https://github.com/justrach/turboAPI.git . \
    && git clone --depth 1 https://github.com/justrach/dhi.git /dhi

# Install Python package
RUN pip3.14t install -e "./python[dev]" 2>/dev/null || pip3.14t install -e "./python" || true

# Build Zig native backend
RUN python3.14t zig/build_turbonet.py \
    && cp zig/zig-out/lib/libturbonet.so python/turboapi/turbonet.cpython-314t-x86_64-linux-gnu.so 2>/dev/null || true

# Copy benchmark app
COPY app.py /turboapi/app.py

EXPOSE 8080

CMD ["python3.14t", "/turboapi/app.py"]
