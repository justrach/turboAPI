// pgvector support — decodes vector binary format and serializes to JSON.
// Binary format: int16 dim, int16 unused, float32[dim] values (big-endian).
// SIMD-accelerated: uses @Vector for batch float32 endian conversion.

const std = @import("std");

pub const Vector = struct {
    // pgvector registers dynamically — OID varies per database.
    // Use configureVectorOid() at startup to set it.
    pub var oid_decimal: i32 = 0;

    dim: u16,
    values: []const f32,
    // Raw data pointer — values are decoded on demand via SIMD
    raw: []const u8,

    pub fn decode(data: []const u8) Vector {
        if (data.len < 4) return .{ .dim = 0, .values = &.{}, .raw = data };
        const dim = std.mem.readInt(u16, data[0..2], .big);
        // skip unused (bytes 2-3)
        return .{
            .dim = dim,
            .values = &.{}, // lazy — use toFloats() or writeJson()
            .raw = data,
        };
    }

    /// Decode all float32 values using SIMD batch conversion.
    /// Caller must free the returned slice.
    pub fn toFloats(self: Vector, alloc: std.mem.Allocator) ![]f32 {
        const dim = self.dim;
        if (dim == 0) return &.{};
        const float_data = self.raw[4..]; // skip dim + unused
        const result = try alloc.alloc(f32, dim);

        // SIMD path: process 4 floats at a time using @Vector
        const simd_width = 4;
        const simd_batches = dim / simd_width;

        var i: usize = 0;
        while (i < simd_batches) : (i += 1) {
            const base = i * simd_width * 4;
            // Load 4 big-endian i32s and reinterpret as f32
            var ints: @Vector(simd_width, i32) = undefined;
            inline for (0..simd_width) |j| {
                const offset = base + j * 4;
                ints[j] = std.mem.readInt(i32, float_data[offset..][0..4], .big);
            }
            // Bitcast i32 vector to f32 vector
            const floats: @Vector(simd_width, f32) = @bitCast(ints);
            inline for (0..simd_width) |j| {
                result[i * simd_width + j] = floats[j];
            }
        }

        // Scalar remainder
        var k: usize = simd_batches * simd_width;
        while (k < dim) : (k += 1) {
            const offset = k * 4;
            const n = std.mem.readInt(i32, float_data[offset..][0..4], .big);
            result[k] = @bitCast(n);
        }

        return result;
    }

    /// Write vector as JSON array: [0.1, 0.2, 0.3, ...]
    /// SIMD-accelerated endian conversion.
    pub fn writeJson(self: Vector, buf: []u8) usize {
        const dim = self.dim;
        if (dim == 0) {
            @memcpy(buf[0..2], "[]");
            return 2;
        }

        const float_data = self.raw[4..];
        var pos: usize = 0;
        buf[pos] = '[';
        pos += 1;

        // SIMD batch decode + format
        const simd_width = 4;
        const simd_batches = dim / simd_width;

        var batch: usize = 0;
        while (batch < simd_batches) : (batch += 1) {
            const base = batch * simd_width * 4;
            var ints: @Vector(simd_width, i32) = undefined;
            inline for (0..simd_width) |j| {
                const offset = base + j * 4;
                ints[j] = std.mem.readInt(i32, float_data[offset..][0..4], .big);
            }
            const floats: @Vector(simd_width, f32) = @bitCast(ints);

            inline for (0..simd_width) |j| {
                if (batch > 0 or j > 0) {
                    buf[pos] = ',';
                    pos += 1;
                }
                const s = std.fmt.bufPrint(buf[pos..], "{d}", .{floats[j]}) catch break;
                pos += s.len;
            }
        }

        // Scalar remainder
        var k: usize = simd_batches * simd_width;
        while (k < dim) : (k += 1) {
            if (k > 0) {
                buf[pos] = ',';
                pos += 1;
            }
            const offset = k * 4;
            const n = std.mem.readInt(i32, float_data[offset..][0..4], .big);
            const v: f32 = @bitCast(n);
            const s = std.fmt.bufPrint(buf[pos..], "{d}", .{v}) catch break;
            pos += s.len;
        }

        buf[pos] = ']';
        pos += 1;
        return pos;
    }

    /// Compute L2 distance between two vectors using SIMD.
    pub fn l2Distance(self: Vector, other: Vector, alloc: std.mem.Allocator) !f32 {
        if (self.dim != other.dim) return error.DimensionMismatch;
        const a = try self.toFloats(alloc);
        defer alloc.free(a);
        const b = try other.toFloats(alloc);
        defer alloc.free(b);

        const dim = self.dim;
        const simd_width = 4;
        const simd_batches = dim / simd_width;
        var sum: @Vector(simd_width, f32) = @splat(0);

        var i: usize = 0;
        while (i < simd_batches) : (i += 1) {
            var va: @Vector(simd_width, f32) = undefined;
            var vb: @Vector(simd_width, f32) = undefined;
            inline for (0..simd_width) |j| {
                va[j] = a[i * simd_width + j];
                vb[j] = b[i * simd_width + j];
            }
            const diff = va - vb;
            sum += diff * diff;
        }

        var total: f32 = @reduce(.Add, sum);

        // Scalar remainder
        var k: usize = simd_batches * simd_width;
        while (k < dim) : (k += 1) {
            const diff = a[k] - b[k];
            total += diff * diff;
        }

        return @sqrt(total);
    }

    /// Compute cosine similarity between two vectors using SIMD.
    pub fn cosineSimilarity(self: Vector, other: Vector, alloc: std.mem.Allocator) !f32 {
        if (self.dim != other.dim) return error.DimensionMismatch;
        const a = try self.toFloats(alloc);
        defer alloc.free(a);
        const b = try other.toFloats(alloc);
        defer alloc.free(b);

        const dim = self.dim;
        const simd_width = 4;
        const simd_batches = dim / simd_width;
        var dot_sum: @Vector(simd_width, f32) = @splat(0);
        var a_sq_sum: @Vector(simd_width, f32) = @splat(0);
        var b_sq_sum: @Vector(simd_width, f32) = @splat(0);

        var i: usize = 0;
        while (i < simd_batches) : (i += 1) {
            var va: @Vector(simd_width, f32) = undefined;
            var vb: @Vector(simd_width, f32) = undefined;
            inline for (0..simd_width) |j| {
                va[j] = a[i * simd_width + j];
                vb[j] = b[i * simd_width + j];
            }
            dot_sum += va * vb;
            a_sq_sum += va * va;
            b_sq_sum += vb * vb;
        }

        var dot: f32 = @reduce(.Add, dot_sum);
        var a_sq: f32 = @reduce(.Add, a_sq_sum);
        var b_sq: f32 = @reduce(.Add, b_sq_sum);

        // Scalar remainder
        var k: usize = simd_batches * simd_width;
        while (k < dim) : (k += 1) {
            dot += a[k] * b[k];
            a_sq += a[k] * a[k];
            b_sq += b[k] * b[k];
        }

        const denom = @sqrt(a_sq) * @sqrt(b_sq);
        if (denom == 0) return 0;
        return dot / denom;
    }
};
