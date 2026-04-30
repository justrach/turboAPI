// This example attempts to demonstrate how both library developers and
// application developers can use this lirary.

// The "lib" subfolder emulates a library.

// Application developers can also define their own "metric" for their own
// application-specifie dmtrics

const std = @import("std");
const m = @import("metrics");

// simulates a library that has metrics
const lib = @import("lib/lib.zig");

pub fn main() !void {
	var gpa = std.heap.GeneralPurposeAllocator(.{}){};
	const allocator = gpa.allocator();

	// The application initializes the metrics for all the libraries it wishes
	// to get metrics from. Optionally, the application can force a metric
	// name prefix and can exclude specific metrics
	try lib.initializeMetrics(allocator, .{
		.prefix = "",    // default to ""
		.exclude = null, // defaults to null
	});

	// this will use some of the libraries metrics
	try lib.doSomething();

	// the application can output the library metric to a writer
	var buffer: [1024]u8 = undefined;
	var stdout = std.fs.File.stdout().writerStreaming(&buffer);
	try lib.writeMetrics(&stdout.interface);
	try stdout.interface.flush();
	// try anotherLib.writeMetrics(writer);
}


