# Prometheus Metric Library for Zig
This library is designed for both library and application developers. I do hope to streamline setup when comptime allocations are allowed.

It supports, counters, gauges and histograms and the labeled-variant of each.

Please see the example project. It demonstrates how a <a href="https://github.com/karlseguin/metrics.zig/blob/master/example/lib/metrics.zig">library developer</a>, and how an <a href="https://github.com/karlseguin/metrics.zig/blob/master/example/main.zig">application developer</a> can initialize and output them.</a>

## Metric Setup
Setup is a bit tedious, and I welcome suggestions for improvement. 

Let's start with a basic example. While the metrics within this library can be used directly, I believe that each library/application should create its own `Metrics` struct that encapsulates all metrics. A global instance of this struct can be created and initialized at comptime into a "noop" state. 

```zig
const m = @import("metrics");

// defaults to noop metrics, making this safe to use
// whether or not initializeMetrics is called
var metrics = m.initializeNoop(Metrics);

const Metrics = struct {
    // counter can be a unsigned integer or floats
    hits: m.Counter(u32),

    // gauge can be an integer or float
    connected: m.Gauge(u16),
};

// meant to be called within the application
pub fn hit() void {
    metrics.hits.incr();
}

// meant to be called within the application
pub fn connected(value: u16) void {
    metrics.connected.set(value);
}

// meant to be called once on application startup
pub fn initializeMetrics(comptime opts: m.RegistryOpts) !void {
    metrics = .{
        .hits = m.Counter(u32).init("hits", .{}, opts),
        .connected = m.Gauge(u16).init("connected", .{}, opts),
    };
}

// thread safe
pub fn writeMetrics(writer: *std.io.Writer) !void {
    return m.write(&metrics, writer);
}
```

The call to `m.initializeNoop(Metrics)` creates a `Metrics` and initializes each metric (`hits`, `connected` and `latency`) to a "noop" implementation (tagged unions are used). The `initializeMetrics` is called on application startup and sets these metrics to real implementation. 

For library developers, this means their global metrics are always safe to use (all methods call noop). For application developers, it gives them control over which metrics to enable.

All metrics take a name and **two options**. Why two options? The first is designed for library developers, the second is designed to give application developers additional control.

Currently the first option has a single field:
* `help: ?[]const u8 = nulls` - Used to generate the `# HELP $HELP` output line

The second option should has two fields:
* `prefix: []const u8 = ""` - Appends `prefix` to the start of each metric name.
* `exclude: ?[]const []const u8 = null` - A list of metric names to exclude (not including the prefix).

`CounterVec`, `GaugeVec`, `Histogram` and `HistogramVec` also require an allocator.

### Note for Library Developers
Library developers are free to change the above as needed. However, having libraries consistently expose an `initializeMetrics` and `writeMetrics` should help application developers.

Library developers should ask their users to call `try initializeMetrics(allocator, .{})` on startup and `try writeMetrics(writer)` to generate the metrics.

The `RegistryOpts` parameter should be supplied by the application and passed to each metric-initializer as-is. 

### Labels (vector-metrics)
Every metric type supports a vectored variant. This allows labels to be attached to metrics. This metrics require an `std.mem.Allocator` and, as you'll see in the metric API section, most of their methods can fail.

```zig
var metrics = m.initializeNoop(Metrics);

const Metrics = struct {
    hits: m.CounterVec(u32, struct{status: u16, name: []const u8}),
};

// All labeled metrics require an allocator
pub fn initializeMetrics(allocator: Allocator, opts: m.RegistryOpts) !void {
    metrics = .{
        .hits = try m.CounterVec(u32, struct{status: u16, name: []const u8}).init(allocator, "hits", .{}, opts),
    };
}
```

The labels are strongly types. Valid label types are: `ErrorSet`, `Enum`, `Type`, `Bool`, `Int` and `[]const u8`

The `CounterVec(u32, ...)` has to be typed twice: once in the definition of `Metrics` and once in `initializeMetrics`. This can be improved slightly.

```zig
var metrics = m.initializeNoop(Metrics);

const Metrics = struct {
    hits: Hits,

    const Hits = m.CounterVec(u32, struct{status: u16, name: []const u8});
};

pub fn initializeMetrics(allocator: Allocator, opts: m.RegistryOpts) !void {
    metrics = .{
        .hits = try Metrics.Hits.init(allocator, "hits", .{}, opts),
    };
}

// Labels are compile-time checked. Using "anytype" here
// is just lazy so we don't have to declare the label structure
pub fn hit(labels: anytype) !void {    
    return metrics.hits.incr(labels);
}
```

The above would be called as:

```zig
// import your metrics file
const metrics = @import("metrics.zig");
metrics.hit(.{.status = 200, .path = "/about.txt"});
```

Internally, every metric is a union between a "noop" and an actual implementation. This allows metrics to be globally initialized as noop and then enabled on startup. The benefit of this approach is that library developers can safely and easily use their metrics whether or not the application has enabled them.

### Histograms
Histograms are setup like `Counter` and `Gauge`, and have a vectored-variant, but they require a comptime list of buckets:

```zig
const Metrics = struct {
    latency: Latency,

    const Latency = m.Histogram(f32, &.{0.005, 0.01, 0.05, 0.1, 0.25, 1, 5, 10});
};

pub fn initializeMetrics(opts: m.RegistryOpts) !void {
    metrics = .{
        .latency = Metrics.Latency.init("hits", .{}, opts),
    };
}
```

The `HistogramVec` is even more verbose, requiring the label struct and bucket list. And, like all vectored metrics, requires an `std.mem.Allocator` and can fail:

```zig
var metrics = m.initializeNoop(Metrics);

const Metrics = struct {
    latency: Latency,

    const Latency = m.HistogramVec(
        u32,
        struct{path: []const u8},
        &.{5, 10, 25, 50, 100, 250, 500, 1000}
    );
};

pub fn initializeMetrics(allocator: Allocator, opts: m.RegistryOpts) !void {
    metrics = .{
        .latency = try Metrics.Latency.init(allocator, "hits", .{}, opts),
    };
}

// Labels are compile-time checked. Using "anytype" here
// is just lazy so we don't have to declare the label structure
// Would be called as:
//   @import("metrics.zig").recordLatency(.{.path = "robots.txt"}, 2);
pub fn recordLatency(labels: anytype, value: u32) !void {
    return metrics.latency.observe(labels, value);
}
```

## Metrics

### Utility
The package exposes the following utility functions.

#### `initializeNoop(T) T`
Creates an initializes metric `T` with `noop` implementation of every metric field. `T` should contain only metrics (`Counter`, `Gauge`, `Historgram` or their vectored variants) and primitive fields (int, bool, []const u8, enum, float). 

`initializeNoop(T)` will set any non-metric field to its default value.

This method is designed to allow a global "metrics" instance to exist and be safe to use within libraries.

#### `write(metrics: anytype, writer: *std.Io.Writer) !void`
Calls the `write(writer) !void` method on every metric field within `metrics`.

Library developers are expected to wrap this method in a `writeMetric(writer: *std.io.Writer) !void` function. This function requires a pointer to your metrics.

### Counter(T)
A `Counter(T)` is used for incrementing values. `T` can be an unsigned integer or a float. Its two main methods are `incr()` and `incrBy(value: T)`. `incr()` is a short version of `incrBy(1)`.

#### `init(comptime name: []const, comptime opts: Opts, comptime ropts: RegistryOpts) !Counter(T)`
Initializes the counter. 

Opts is:
* `help: ?[]const` - optional help text to include in the prometheus output


#### `incr(self: *Counter(T)) void`
Increments the counter by 1.

#### `incrBy(self: *Counter(T), value: T) void`
Increments the counter by `value`.

#### `write(self: *const Counter(T), writer: *std.io.Writer) !void`
Writes the counter to `writer`.

### CounterVec(T, L)
A `CounterVec(T, L)` is used for incrementing values with labels. `T` can be an unsigned integer or a float. `L` must be a struct where the field names and types will define the lables. Its two main methods are `incr(labels: L)` and `incrBy(labels: L, value: T)`. `incr(L)` is a short version of `incrBy(L, 1)`.

#### `init(allocator: Allocator, comptime name: []const, comptim eopts: Opts, comptime ropts: RegistryOpts) !CounterVec(T, L)`
Initializes the counter. Name must be given at comptime. 

Opts is:
* `help: ?[]const` - optional help text to include in the prometheus output

#### `deinit(self: *CounterVec(T, L)) void`
Deallocates the counter

#### `incr(self: *CounterVec(T, L), labels: L) !void`
Increments the counter by 1. Vectored metrics can fail.

#### `incrBy(self: *CounterVec(T, L), labels: L, value: T) !void`
Increments the counter by `value`. Vectored metrics can fail.

#### `remove(self: *CounterVec(T, L), labels: L) void`
Removes the labeled value from the counter. Safe to call if `labels` is not an existing label.

#### `write(self: *CounterVec(T, L), writer: *std.io.Writer) !void`
Writes the counter to `writer`.

### Gauge(T)
A `Gauge(T)` is used for setting values. `T` can be an integer or a float. Its main methods are `incr()`, `incrBy(value: T)` and `set(value: T)`. `incr()` is a short version of `incrBy(1)`.

#### `init(comptime name: []const, comptime opts: Opts, comptime ropts: RegistryOpts) !Gauge(T)`
Initializes the gauge. Name must be given at comptime. 

Opts is:
* `help: ?[]const` - optional help text to include in the prometheus output

#### `incr(self: *Gauge(T)) void`
Increments the gauge by 1.

#### `incrBy(self: *Gauge(T), value: T) void`
Increments the gauge by `value`.

#### `set(self: *Gauge(T), value: T) void`
Sets the the gauge to `value`.

#### `write(self: *Gauge(T), writer: *std.io.Writer) !void`
Writes the gauge to `writer`.

### GaugeVec(T, L)
A `GaugeVec(T, L)` is used for incrementing values with labels. `T` can be an integer or a float. `L` must be a struct where the field names and types will define the lables. Its main methods are `incr(labels: L)`, `incrBy(labels: L, value: T)` and `set(labels: L, value: T)`. `incr(L)` is a short version of `incrBy(L, 1)`.

#### `init(allocator: Allocator, comptime name: []const, comptime opts: Opts, comptime ropts: RegistryOpts) !GaugeVec(T, L)`
Initializes the gauge. Name must be given at comptime. 

Opts is:
* `help: ?[]const` - optional help text to include in the prometheus output

#### `deinit(self: *GaugeVec(T, L)) void`
Deallocates the gauge

#### `incr(self: *GaugeVec(T, L), labels: L) !void`
Increments the gauge by 1. Vectored metrics can fail.

#### `incrBy(self: *GaugeVec(T, L), labels: L, value: T) !void`
Increments the gauge by `value`. Vectored metrics can fail.

#### `set(self: *GaugeVec(T, L), labels: L, value: T) !void`
Sets the gauge to `value`. Vectored metrics can fail.

#### `remove(self: *GaugeVec(T, L), labels: L) void`
Removes the labeled value from the gauge. Safe to call if `labels` is not an existing label.

#### `write(self: *GaugeVec(T, L), writer: *std.io.Writer) !void`
Writes the gauge to `writer`.

### Histogram(T, []T)
A `Histogram(T, []T)` is used  to track the size and frequency of events. `T` can be an unsigned integer or a float. Its main methods is `observe(T)`.

Observed valued will fall within one of the provided buckets, `[]T`. The buckets must be in ascending order. A final "infinite" bucket *should not* be provided.

#### `init(comptime name: []const, comptime opts: Opts, comptime ropts: RegistryOpts) !Histogram(T, []T)`
Initializes the histogram. Name must be given at comptime. 

Opts is:
* `help: ?[]const` - optional help text to include in the prometheus output

#### `observe(self: *Histogram(T, []T), value: T) void`
Observes `value`, bucketing it based on the provided comptime buckets.

#### `write(self: *Histogram(T, []T), writer: *std.io.Writer) !void`
Writes the histogram to `writer`.

### Histogram(T, L, []T)
A `Histogram(T, L, []T)` is used  to track the size and frequency of events. `T` can be an unsigned integer or a float. `L` must be a struct where the field names and types will define the lables. Its main methods is `observe(T)`.

Observed valued will fall within one of the provided buckets, `[]T`. The buckets must be in ascending order. A final "infinite" bucket *should not* be provided.

#### `init(allocator: Allocator, comptime name: []const, comptime opts: Opts, comptime ropts: RegistryOpts) !Histogram(T, L, []T)`
Initializes the histogram. Name must be given at comptime. 

Opts is:
* `help: ?[]const` - optional help text to include in the prometheus output

#### `deinit(self: *Histogram(T, L, []T)) void`
Deallocates the histogram

#### `observe(self: Histogram(T, L, []T), value: T) void`
Observes `value`, bucketing it based on the provided comptime buckets.

#### `remove(self: *Histogram(T, L, []T), labels: L) void`
Removes the labeled value from the histogram. Safe to call if `labels` is not an existing label.

#### `write(self: Histogram(T, L, []T), writer: *std.io.Writer) !void`
Writes the histogram to `writer`.
