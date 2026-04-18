// This folder simulates a 3rd party library that the application, main.zig
// is using.

const metrics = @import("metrics.zig");

// Expose initializeMetrics to give control to the application over whether or
// not the library metrics should be enabled.
pub const initializeMetrics = metrics.initialize;

// Expose writeMetrics to the application
pub const writeMetrics = metrics.write;

// We want to collect metrics about this
pub fn doSomething() !void {
  metrics.active(10);

  // vectored metrics can fail, hence the try
  try metrics.hit(.{.status = 200, .path = "/robots.txt"});

  try metrics.latency(.{.path = "/"}, 3.2);
}
