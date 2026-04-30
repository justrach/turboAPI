//! Linux io_uring accept loop for TurboAPI.
//!
//! ## Status (PR #1 — accept-loop only)
//!
//! What this module does today:
//!   * Sets up a single io_uring (per accept thread) on Linux ≥ 5.19.
//!   * Posts an `IORING_OP_ACCEPT_MULTISHOT` on the listen fd, so the kernel
//!     produces a CQE per accepted connection without us re-arming the SQE.
//!   * For every accepted fd, hands the connection off to the existing
//!     `ConnectionPool` (per-worker thread + synchronous recv/send) by wrapping
//!     the raw fd back into a `std.Io.net.Stream`.
//!
//! What this module does *not* do yet (deliberately staged):
//!   * `IORING_OP_RECV` / `RECV_MULTISHOT` for the per-connection request read.
//!   * `IORING_OP_SEND` / `SEND_ZC` for the per-connection response write.
//!   * Per-worker thread-per-core io_uring rings (we still funnel through one
//!     accept ring; per-connection work then lives on the existing pool).
//!   * Linked SQEs to fuse `recv → send → recv` into a single submit.
//!
//! Those are tracked as follow-up PRs against `release/beta-v1.0.30`. They
//! are the paths where io_uring actually moves throughput; the accept loop
//! alone is mostly a correctness / scaffolding step.
//!
//! ## Compile and runtime gating
//!
//!   * Compiles on every target (so `zig build` stays portable). The Linux
//!     std.os.linux.IoUring import is unconditional — Zig's stdlib defines
//!     the type on all targets, but `init()` will fail on non-Linux.
//!   * `Available` is `true` only on Linux.
//!   * `enabled()` combines `Available` with the `-Diouring=true` build flag.
//!     When `enabled()` is false, callers must keep using the existing
//!     blocking-accept path.
//!
//! ## Honest perf claim
//!
//! This module has *not* been benchmarked. Per AGENTS.md, no benchmark
//! tables, comparisons, or "vs framework X" claims should appear in docs,
//! release notes, or the PR description until we have a real Linux run with
//! the bench-frameworks script and recorded artifacts. Saying "io_uring is
//! enabled" is fine; saying "io_uring makes TurboAPI N× faster" is not,
//! until we have real numbers.

const std = @import("std");
const builtin = @import("builtin");

const build_options = @import("turbo_build_options");

/// True on Linux targets. Other targets get a stub that always errors.
pub const Available: bool = builtin.os.tag == .linux;

/// True only when both the build flag *and* the runtime target are Linux.
pub inline fn enabled() bool {
    return Available and build_options.iouring_enabled;
}

/// Default submission-queue depth. Picked to match nanoapi and liburing
/// examples; can be tuned later via env var or `Options`.
pub const DEFAULT_SQ_ENTRIES: u16 = 1024;

/// Errors a caller can see from this module.
pub const Error = error{
    /// `enabled()` was false when the caller asked us to run.
    NotEnabled,
    /// Kernel returned EINVAL / EPERM on `io_uring_setup` — usually means
    /// the running kernel is older than 5.19 or io_uring is disabled
    /// (`/proc/sys/kernel/io_uring_disabled`).
    SetupFailed,
    /// Submitting the multishot accept SQE failed.
    AcceptSubmitFailed,
};

/// Linux-only implementation. Kept in its own struct so non-Linux callers
/// can still reference `Available`/`enabled()` without forcing the type to
/// instantiate.
pub const Linux = if (Available) struct {
    const linux = std.os.linux;
    const posix = std.posix;
    const IoUring = linux.IoUring;

    pub const AcceptCallback = *const fn (ctx: *anyopaque, fd: posix.fd_t) void;

    pub const AcceptLoop = struct {
        ring: IoUring,
        listen_fd: posix.fd_t,
        on_accept: AcceptCallback,
        on_accept_ctx: *anyopaque,
        running: std.atomic.Value(bool) = std.atomic.Value(bool).init(true),

        /// Initialize the ring. `listen_fd` must already be a non-blocking
        /// socket bound + listening on the desired address.
        pub fn init(
            listen_fd: posix.fd_t,
            on_accept: AcceptCallback,
            on_accept_ctx: *anyopaque,
            entries: u16,
        ) Error!AcceptLoop {
            const ring = IoUring.init(entries, 0) catch return Error.SetupFailed;
            return .{
                .ring = ring,
                .listen_fd = listen_fd,
                .on_accept = on_accept,
                .on_accept_ctx = on_accept_ctx,
            };
        }

        pub fn deinit(self: *AcceptLoop) void {
            self.ring.deinit();
        }

        /// Submit the multishot accept and pump the completion queue until
        /// `stop()` is called from another thread.
        pub fn run(self: *AcceptLoop) Error!void {
            // Tag the multishot accept CQE with user_data == 0 so we can
            // distinguish it from per-connection ops in future PRs.
            _ = self.ring.accept_multishot(0, self.listen_fd, null, null, 0) catch
                return Error.AcceptSubmitFailed;
            _ = self.ring.submit() catch return Error.AcceptSubmitFailed;

            var cqes: [64]linux.io_uring_cqe = undefined;
            while (self.running.load(.acquire)) {
                // Block until at least one CQE arrives. `copy_cqes` wraps
                // io_uring_enter(GETEVENTS); EINTR is retried inside the
                // stdlib helper.
                const n = self.ring.copy_cqes(&cqes, 1) catch |err| switch (err) {
                    error.SignalInterrupt => continue,
                    else => return Error.SetupFailed,
                };

                for (cqes[0..n]) |cqe| {
                    if (cqe.user_data != 0) continue; // future: per-conn ops
                    if (cqe.res < 0) {
                        // Negative res = -errno. Common cases: -EINTR retries,
                        // -EAGAIN can't happen on multishot accept. Anything
                        // else, log and re-arm.
                        const errno_val: i32 = -cqe.res;
                        if (errno_val == @intFromEnum(linux.E.INTR)) continue;
                        // Re-arm and continue; the listen fd is still valid.
                        try self.rearmAccept();
                        continue;
                    }

                    // Multishot returns the new fd directly in cqe.res.
                    const fd: posix.fd_t = @intCast(cqe.res);
                    self.on_accept(self.on_accept_ctx, fd);

                    // If the kernel cleared the multishot bit (e.g. ring
                    // pressure), re-arm.
                    if ((cqe.flags & linux.IORING_CQE_F_MORE) == 0) {
                        try self.rearmAccept();
                    }
                }
            }
        }

        /// Signal the loop in `run` to exit. Safe to call from another
        /// thread.
        pub fn stop(self: *AcceptLoop) void {
            self.running.store(false, .release);
        }

        fn rearmAccept(self: *AcceptLoop) Error!void {
            _ = self.ring.accept_multishot(0, self.listen_fd, null, null, 0) catch
                return Error.AcceptSubmitFailed;
            _ = self.ring.submit() catch return Error.AcceptSubmitFailed;
        }
    };
} else struct {
    // Non-Linux placeholder so the module type-checks everywhere.
    pub const AcceptCallback = *const fn (ctx: *anyopaque, fd: i32) void;
    pub const AcceptLoop = struct {
        pub fn init(
            _: i32,
            _: AcceptCallback,
            _: *anyopaque,
            _: u16,
        ) Error!AcceptLoop {
            return Error.NotEnabled;
        }
        pub fn deinit(_: *AcceptLoop) void {}
        pub fn run(_: *AcceptLoop) Error!void {
            return Error.NotEnabled;
        }
        pub fn stop(_: *AcceptLoop) void {}
    };
};

test "iouring module compiles on every target" {
    // The whole point of this test is to make sure `Available`, `enabled()`
    // and `Linux.AcceptLoop` all type-check on the host build, regardless of
    // OS. Real behavior is exercised by the Linux integration tests in a
    // follow-up PR.
    _ = Available;
    _ = enabled();
    _ = Linux.AcceptLoop;
}
