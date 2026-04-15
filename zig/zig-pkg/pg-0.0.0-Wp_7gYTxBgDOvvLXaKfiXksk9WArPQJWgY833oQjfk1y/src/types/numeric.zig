const std = @import("std");
const buffer = @import("buffer");
const lib = @import("../lib.zig");
const types = @import("../types.zig");

const Encode = types.Encode;

const math = std.math;

// Until Zig has a native decimal type, or a third party library becomes de
// facto standard, this library is going to have half-baked numeric support.
// Specifically, we capture the PG wire-format for the numeric as-is. If you
// need numeric-precision, then you'll have to make due with this and interpret
// the data yourself. However, we do provide convience functions to get an f64
// or a string value from the numeric.
//
// PG's format ends with a group of base 10_000 digits. So to represent the
// number 3950.123456, `numeric.digits` will be:
//   {0x0F, 0x6E, 0x04, 0xD2, 0x15, 0xE0}
//    3950        1234        5600
//
// In this case `number_of_digits` will be 3. Take note: both `digits` and
// `number_of_digits` are base 10_000.
//
// `weight` is the weight of the first digit. For 3950.123456, the weight will
// be 0, so we end up with 3950 * (10_000 ^ 0).
//
// `scale` is the display scale, and represents the # of BASE 10 digits to print
// after the decimal. At first glance, this might seem redundant, but there's
// a difference between 3950.123456 and 3950.12345600. The latter indicates a
// greater degree of precision. `scale` can also be larger than the number of
// digits we have, which is used to indicate additional 0s.

pub const Numeric = struct {
    pub const encoding = &types.binary_encoding;
    pub const oid = types.OID.make(1700);

    number_of_digits: u16,
    weight: i16,
    sign: Sign,
    scale: u16,
    // this is tied to the current row and is only valid while the row is valid
    // calling `next()`, `deinit()` `drain()` on there result, or `deinit()` on
    // a QueryRow will invalidate this.
    digits: []const u8,

    const Sign = enum {
        nan,
        inf,
        negative,
        positive,
        negativeInf,
    };

    pub fn encode(value: anytype, buf: *buffer.Buffer, format_pos: usize) !void {
        buf.writeAt(encoding, format_pos);
        return encodeBuf(value, buf);
    }

    pub fn encodeBuf(value: anytype, buf: *buffer.Buffer) !void {
        const T = @TypeOf(value);
        if (T == comptime_float) {
            return encodeValue(value, buf);
        }

        const TT = switch (@typeInfo(T)) {
            .optional => |opt| opt.child,
            else => T,
        };

        var v: TT = undefined;
        if (comptime @typeInfo(T) == .optional) {
            v = value orelse return encodeValidString("null", buf);
        } else {
            v = value;
        }

        if (math.isNan(v)) {
            return encodeNaN(buf);
        }
        if (math.isNegativeInf(v)) {
            return encodeNegativeInf(buf);
        }
        if (math.isInf(v)) {
            return encodeInf(buf);
        }

        return encodeValue(v, buf);
    }

    fn encodeValue(value: anytype, buf: *buffer.Buffer) !void {
        // turn our float into a string
        var str_buf: [512]u8 = undefined;
        const slice = try std.fmt.bufPrint(&str_buf, "{d}", .{value});
        return encodeValidString(slice, buf);
    }

    pub fn decode(comptime fail_mode: lib.FailMode, data: []const u8, data_oid: i32) if (fail_mode == .unsafe) Numeric else lib.TypeError!Numeric {
        lib.verifyDecodeType(fail_mode, Numeric, &.{Numeric.oid.decimal}, data_oid) catch |err| {
            if (fail_mode == .unsafe) unreachable;
            return err;
        };

        lib.assert(data.len >= 8);
        return decodeKnown(data);
    }

    pub fn decodeKnown(data: []const u8) Numeric {
        return .{
            .number_of_digits = std.mem.readInt(u16, data[0..2], .big),
            .weight = std.mem.readInt(i16, data[2..4], .big),
            .sign = switch (std.mem.readInt(u16, data[4..6], .big)) {
                0x0000 => .positive,
                0x4000 => .negative,
                0xd000 => .inf,
                0xf000 => .negativeInf,
                else => .nan, // 0xc000
            },
            .scale = std.mem.readInt(u16, data[6..8], .big),
            .digits = data[8..],
        };
    }

    pub fn decodeKnownToFloat(data: []const u8) f64 {
        return decodeKnown(data).toFloat();
    }

    pub fn toFloat(self: Numeric) f64 {
        switch (self.sign) {
            .nan => return math.nan(f64),
            .inf => return math.inf(f64),
            .negativeInf => return -math.inf(f64),
            else => {},
        }

        var value: f64 = 0;
        var weight = self.weight;
        var digits: []const u8 = self.digits;
        for (0..self.number_of_digits) |_| {
            const t = std.mem.readInt(i16, digits[0..2], .big);
            value += @as(f64, @floatFromInt(t)) * math.pow(f64, 10_000, @floatFromInt(weight));
            digits = digits[2..];
            weight -= 1;
        }

        return if (self.sign == .negative) -value else value;
    }

    pub fn estimatedStringLen(self: Numeric) usize {
        // for the decimal point
        var l: usize = 1;
        switch (self.sign) {
            .nan => return 3,
            .inf => return 3,
            .negativeInf => return 4,
            .negative => l += 1,
            .positive => {},
        }

        // max size per base-10000 digit
        if (self.number_of_digits == 0) {
            return l + 2; // 0.0  but we already added the decimal place
        }

        l += self.number_of_digits * 4;
        // there's no integer in the number, but our string output will have
        // a leading 0  (so it'll be 0.123 instead of just .123)
        if (self.weight < 0) {
            l += 1;
        }

        return l;
    }

    pub fn toString(self: Numeric, buf: []u8) ![]u8 {
        switch (self.sign) {
            .nan => {
                @memcpy(buf[0..3], "nan");
                return buf[0..3];
            },
            .inf => {
                @memcpy(buf[0..3], "inf");
                return buf[0..3];
            },
            .negativeInf => {
                @memcpy(buf[0..4], "-inf");
                return buf[0..4];
            },
            else => {},
        }

        var pos: usize = 0;
        var weight = self.weight;
        var digits: []const u8 = self.digits;
        const number_of_digits = self.number_of_digits;

        if (self.sign == .negative) {
            buf[0] = '-';
            pos += 1;
        }

        if (number_of_digits == 0) {
            const end = pos + 3;
            @memcpy(buf[pos..end], "0.0");
            return buf[0..end];
        }

        // do the integer part first
        if (weight < 0) {
            buf[pos] = '0';
            pos += 1;
        } else {
            while (weight >= 0) {
                if (digits.len == 0) {
                    const end = pos + 4;
                    @memcpy(buf[pos..end], "0000");
                    pos = end;
                } else {
                    const t = std.mem.readInt(i16, digits[0..2], .big);
                    pos += (try std.fmt.bufPrint(buf[pos..], "{d}", .{t})).len;
                    digits = digits[2..];
                }
                weight -= 1;
            }
        }

        buf[pos] = '.';
        pos += 1;

        // now the fraction
        if (digits.len == 0) {
            buf[pos] = '0';
            pos += 1;
        } else {
            while (digits.len > 0) {
                const t = std.mem.readInt(i16, digits[0..2], .big);
                if (t < 10) {
                    buf[pos + 2] = '0';
                    buf[pos + 1] = '0';
                    buf[pos] = '0';
                    pos += 3;
                } else if (t < 100) {
                    buf[pos + 1] = '0';
                    buf[pos] = '0';
                    pos += 2;
                } else if (t < 1000) {
                    buf[pos] = '0';
                    pos += 1;
                }
                pos += (try std.fmt.bufPrint(buf[pos..], "{d}", .{t})).len;
                digits = digits[2..];
            }
        }

        // we wrote the fraction in 4-digit groups, but our scale (aka display scale)
        // might indicate that we should have less precision. For example, we might
        // have written 0.1230, but the scale might be 3, in which case we should
        // have written 0.123.
        const display_scale = @mod(self.scale, 4);
        if (display_scale > 0) {
            pos -= 4 - display_scale;
        }
        return buf[0..pos];
    }
};

// encode a string that we know isn't NaN, Inf or -Inf.
fn encodeValidString(str: []const u8, buf: *buffer.Buffer) !void {
    // the length of our parameter is dynamic, we reserve 4 bytes to fill in once
    // we know what our length is.
    const length_state = try Encode.variableLengthStart(buf);

    // we have 8 bytes of meta (# of digits, weight, sign and scale) that we
    // don't yet know how to fill up, reserve the space.
    var meta_view = try buf.skip(8);

    // buf now points to 12 bytes ahead of where we started. 4 bytes for the
    // length and 8 bytes for the meta. This is the position where we fill in
    // our base 10000 digits.

    var pos: usize = 0;
    var positive = true;

    if (str[0] == '-') {
        // check this here, so we don't need to check it on each iteration
        pos = 1;
        positive = false;
    }

    // if no decimal, assume this is a whole number
    const decimal_pos = std.mem.indexOfScalarPos(u8, str, pos, '.') orelse str.len;

    // The number of 4-digit groups in our integer
    const integer_groups = blk: {
        // We're going to write the digits of the integer portion of our float. This
        // is base 10_000, so we're going to group them in 4s. Given a number like
        // 12345, there are two ways to group these. The correct way is (1) (2345), the
        // incorrect way is (1234) (5).
        // The correct way will let us recombine the value as
        //   (1 * 10000) + (2345) = 12345
        // The incorrect way would result in
        //   (1234 * 10000) + 5 = 11239
        const integer_digits: u16 = @intCast(decimal_pos - pos);

        // our first group can be 1-4 digits
        const first_group = @mod(integer_digits, 4);
        if (first_group > 0) {
            // if first_group == 0, then it's a full 4-digit group and can be handled
            // by the more general case that follows
            const end = pos + first_group;
            try buf.writeIntBig(u16, generateGroup(str[pos..end]));
            pos = end;
        }

        // At this point, we know that decimal_pos - pos is a multilpe of 4 (possibly
        // 0) and we can handle it 4 digits at a time.
        while (pos < decimal_pos) {
            const end = pos + 4;
            try buf.writeIntBig(u16, generateGroup(str[pos..end]));
            pos = end;
        }

        break :blk try std.math.divCeil(u16, integer_digits, 4);
    };

    // skip decimal point
    pos += 1;

    {
        // Now we do the fraction. This is similar to above, with a different little
        // concern. Given 0.12345, you might thing we need to group as (1234) (5)
        // but actually we need to group as (1234) (5000). Just (5) would mean
        // 0.12340005 (we'd pass {0, 5} as the big-16 encoded base-10000 for that 2nd
        // group).
        // This causes a new problem. There's a difference between 0.12345 and
        // 0.12345000, the latter is indicative of greater precision. This is what
        // the dscale (or just scale) meta parameter resolves. Our dscale will be
        // 5, indicating that the fraction is "12345" and not "12345000"..

        if (str.len > decimal_pos + 4) {
            const loop_end = str.len - 4;
            while (pos < loop_end) {
                const end = pos + 4;
                try buf.writeIntBig(u16, generateGroup(str[pos..end]));
                pos = end;
            }
        }

        if (pos < str.len) {
            const leftover = str.len - pos;
            if (leftover > 0) {
                // we have an incomplete group left over, read comment above for why
                // we're multiplying this
                var group_value = generateGroup(str[pos..]);
                group_value *= switch (leftover) {
                    3 => 10,
                    2 => 100,
                    1 => 1000,
                    else => 1,
                };
                try buf.writeIntBig(u16, group_value);
            }
        }
    }

    {
        // -1 to exclude the decimal point itself
        const display_scale: u16 = if (decimal_pos == str.len) 0 else @intCast(str.len - decimal_pos - 1);

        // Fill in our meta
        // Number of base-10000 digits that we wrote.
        meta_view.writeIntBig(u16, @intCast(integer_groups + try std.math.divCeil(u16, display_scale, 4)));

        // weight is the number of integer groups - 1;
        if (integer_groups == 0 or integer_groups == 1) {
            meta_view.write(&.{ 0, 0 });
        } else {
            meta_view.writeIntBig(u16, integer_groups - 1);
        }

        if (positive) {
            meta_view.write(&.{ 0, 0 });
        } else {
            meta_view.write(&.{ 64, 0 });
        }
        meta_view.writeIntBig(u16, display_scale);
    }

    // fill our our length
    Encode.variableLengthFill(buf, length_state);
}

fn encodeNaN(buf: *buffer.Buffer) !void {
    // 8 length, 0 digits, 0 weight, nan sign, 0 dscale
    return buf.write(&.{ 0, 0, 0, 8, 0, 0, 0, 0, 192, 0, 0, 0 });
}

fn encodeInf(buf: *buffer.Buffer) !void {
    // 8 length, 0 digits, 0 weight, inf sign, 0 dscale
    return buf.write(&.{ 0, 0, 0, 8, 0, 0, 0, 0, 208, 0, 0, 0 });
}

fn encodeNegativeInf(buf: *buffer.Buffer) !void {
    // 8 length, 0 digits, 0 weight, -inf sign, 0 dscale
    return buf.write(&.{ 0, 0, 0, 8, 0, 0, 0, 0, 240, 0, 0, 0 });
}

fn generateGroup(str: []const u8) u16 {
    const number_of_digits = str.len;

    var group_value: u16 = 0;
    for (str, 0..) |c, i| {
        const d = @as(u16, c - '0');
        group_value += switch (number_of_digits - i) {
            4 => d * 1_000,
            3 => d * 100,
            2 => d * 10,
            1 => d,
            else => unreachable,
        };
    }
    return group_value;
}
