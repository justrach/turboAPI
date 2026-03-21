const std = @import("std");
// css.zig — comptime CSS helpers for inline styles and class names.
//
// Usage:
//   const h = mer.h;
//   const css = mer.css;
//
//   // Inline styles — struct fields become CSS properties (snake_case → kebab-case)
//   h.div(.{ .style = css.style(.{
//       .display = "flex",
//       .align_items = "center",
//       .padding = "1rem",
//       .background = "#1a1a2e",
//       .border_radius = "8px",
//       .gap = "0.5rem",
//   }) }, .{ ... })
//
//   // Conditional class names
//   h.div(.{ .class = css.cx(.{ "card", if (is_active) "active" else null, "p-4" }) }, .{ ... })

/// Convert a comptime struct to a CSS inline style string.
/// Field names are converted from snake_case to kebab-case.
///
///   css.style(.{ .border_radius = "8px", .font_size = "14px" })
///   // → "border-radius:8px;font-size:14px"
pub fn style(comptime props: anytype) []const u8 {
    comptime {
        var result: []const u8 = "";
        const fields = @typeInfo(@TypeOf(props)).@"struct".fields;
        for (fields) |field| {
            const value = @field(props, field.name);
            if (result.len > 0) result = result ++ ";";
            result = result ++ snakeToCssProperty(field.name) ++ ":" ++ value;
        }
        return result;
    }
}

/// Concatenate class names, skipping nulls. Comptime version of clsx/classnames.
///
///   css.cx(.{ "card", if (is_active) "active" else null, "p-4" })
///   // → "card active p-4" (if is_active) or "card p-4" (if not)
pub fn cx(comptime classes: anytype) []const u8 {
    comptime {
        var result: []const u8 = "";
        const fields = @typeInfo(@TypeOf(classes)).@"struct".fields;
        for (fields) |field| {
            const val = @field(classes, field.name);
            const T = @TypeOf(val);
            if (T == @TypeOf(null)) continue;
            if (T == ?[]const u8) {
                if (val) |v| {
                    if (result.len > 0) result = result ++ " ";
                    result = result ++ v;
                }
            } else {
                // It's a string literal
                if (result.len > 0) result = result ++ " ";
                result = result ++ val;
            }
        }
        return result;
    }
}

/// Convert a snake_case field name to a CSS kebab-case property name at comptime.
/// "border_radius" → "border-radius", "font_size" → "font-size"
fn snakeToCssProperty(comptime name: []const u8) []const u8 {
    comptime {
        var result: []const u8 = "";
        for (name) |c| {
            result = result ++ (if (c == '_') "-" else &[_]u8{c});
        }
        return result;
    }
}

test "style: single property" {
    comptime try std.testing.expectEqualStrings("color:red", style(.{ .color = "red" }));
}

test "style: multiple properties" {
    comptime try std.testing.expectEqualStrings("display:flex;padding:1rem", style(.{ .display = "flex", .padding = "1rem" }));
}

test "style: snake_case to kebab-case" {
    comptime try std.testing.expectEqualStrings("border-radius:8px;font-size:14px", style(.{ .border_radius = "8px", .font_size = "14px" }));
}

test "cx: basic concatenation" {
    comptime try std.testing.expectEqualStrings("card active p-4", cx(.{ "card", "active", "p-4" }));
}

test "cx: with nulls" {
    comptime try std.testing.expectEqualStrings("card p-4", cx(.{ "card", @as(?[]const u8, null), "p-4" }));
}
