// Shared HTTP types used across turboapi consumers.

/// A parsed HTTP header name-value pair.
/// Slices borrow from the request buffer — do not outlive the request.
pub const HeaderPair = struct {
    name: []const u8,
    value: []const u8,
};
