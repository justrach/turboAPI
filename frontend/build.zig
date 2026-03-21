const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});

    const merjs_dep = b.dependency("merjs", .{
        .target = target,
        .optimize = optimize,
    });
    const mer_mod = merjs_dep.module("mer");

    // Use LOCAL src/main.zig (with our generated/routes.zig)
    const main_mod = b.createModule(.{
        .root_source_file = b.path("src/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    main_mod.addImport("mer", mer_mod);

    // Register app/ pages
    addAppPages(b, main_mod, mer_mod, "app", "app");

    const exe = b.addExecutable(.{ .name = "turboapi-site", .root_module = main_mod });
    b.installArtifact(exe);

    const run = b.addRunArtifact(exe);
    run.step.dependOn(b.getInstallStep());
    if (b.args) |args| run.addArgs(args);
    b.step("serve", "Dev server on localhost:3000").dependOn(&run.step);

    const prerender = b.addRunArtifact(exe);
    prerender.addArg("--prerender");
    prerender.step.dependOn(b.getInstallStep());
    b.step("prerender", "Pre-render to dist/").dependOn(&prerender.step);
}

fn addAppPages(b: *std.Build, main_mod: *std.Build.Module, mer_mod: *std.Build.Module, dir: []const u8, prefix: []const u8) void {
    const layout_path = b.fmt("{s}/layout.zig", .{dir});
    const layout_mod: ?*std.Build.Module = blk: {
        std.fs.cwd().access(layout_path, .{}) catch break :blk null;
        const m = b.createModule(.{ .root_source_file = b.path(layout_path) });
        m.addImport("mer", mer_mod);
        main_mod.addImport(b.fmt("{s}/layout", .{prefix}), m);
        break :blk m;
    };

    if (std.fs.cwd().access(b.fmt("{s}/404.zig", .{dir}), .{})) |_| {
        const m = b.createModule(.{ .root_source_file = b.path(b.fmt("{s}/404.zig", .{dir})) });
        m.addImport("mer", mer_mod);
        if (layout_mod) |lm| m.addImport(b.fmt("{s}/layout", .{prefix}), lm);
        main_mod.addImport(b.fmt("{s}/404", .{prefix}), m);
    } else |_| {}

    var d = std.fs.cwd().openDir(dir, .{ .iterate = true }) catch return;
    defer d.close();
    var walker = d.walk(b.allocator) catch return;
    defer walker.deinit();
    while (walker.next() catch null) |entry| {
        if (entry.kind != .file) continue;
        if (!std.mem.endsWith(u8, entry.path, ".zig")) continue;
        if (std.mem.eql(u8, entry.path, "layout.zig") or std.mem.eql(u8, entry.path, "404.zig")) continue;
        const file_path = b.fmt("{s}/{s}", .{ dir, entry.path });
        const import_name = b.fmt("{s}/{s}", .{ prefix, entry.path[0 .. entry.path.len - 4] });
        const route_mod = b.createModule(.{ .root_source_file = b.path(file_path) });
        route_mod.addImport("mer", mer_mod);
        if (layout_mod) |lm| route_mod.addImport(b.fmt("{s}/layout", .{prefix}), lm);
        main_mod.addImport(import_name, route_mod);
    }
}
