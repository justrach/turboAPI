const mer = @import("mer");

pub const meta: mer.Meta = .{
    .title = "v1.0.28 — TurboAPI",
    .description = "TurboAPI v1.0.28: Zig 0.16 migration, 21 bug fixes, native multipart, structured logging, and 6 new fuzz targets.",
};

pub const prerender = true;

pub fn render(req: mer.Request) mer.Response {
    _ = req;
    return .{
        .status = .ok,
        .content_type = .html,
        .body = html,
    };
}

const html =
    \\<!DOCTYPE html>
    \\<html lang="en">
    \\<head>
    \\  <meta charset="UTF-8">
    \\  <meta name="viewport" content="width=device-width, initial-scale=1.0">
    \\  <title>v1.0.28 — TurboAPI</title>
    \\  <link rel="preconnect" href="https://fonts.googleapis.com">
    \\  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    \\  <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    \\  <style>
    \\    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    \\    :root {
    \\      --bg: #f9f8f6; --bg2: #f2f0ec; --bg3: #e9e5de;
    \\      --dark: #0e0d0b; --dark2: #1a1916; --dark3: #252320;
    \\      --text: #0e0d0b; --muted: #8a8478; --border: #ddd9d2;
    \\      --accent: #e8821a; --accent-dim: rgba(232,130,26,0.15);
    \\      --green: #22c55e; --blue: #3b82f6; --purple: #a855f7;
    \\      --mono: 'JetBrains Mono', monospace;
    \\      --sans: 'Inter', sans-serif;
    \\      --display: 'Space Grotesk', sans-serif;
    \\    }
    \\    html { scroll-behavior: smooth; }
    \\    body { background: var(--bg); color: var(--text); font-family: var(--sans); min-height: 100vh; overflow-x: hidden; }
    \\    a { color: inherit; text-decoration: none; }
    \\
    \\    nav { position: sticky; top: 0; z-index: 100; background: rgba(14,13,11,0.92); backdrop-filter: blur(12px); border-bottom: 1px solid rgba(255,255,255,0.08); }
    \\    .nav-inner { max-width: 1100px; margin: 0 auto; padding: 0 40px; display: flex; align-items: center; justify-content: space-between; height: 60px; }
    \\    .wordmark { font-family: var(--display); font-size: 16px; font-weight: 800; letter-spacing: -0.02em; color: #fff; }
    \\    .wordmark em { font-style: normal; color: var(--accent); }
    \\    .nav-links { display: flex; gap: 32px; align-items: center; }
    \\    .nav-links a { font-size: 13px; font-weight: 500; color: rgba(255,255,255,0.5); transition: color 0.15s; }
    \\    .nav-links a:hover { color: #fff; }
    \\    .nav-cta { font-family: var(--display); font-size: 13px !important; font-weight: 700 !important; color: #fff !important; background: var(--accent); padding: 8px 18px; border-radius: 4px; }
    \\    .nav-cta:hover { opacity: 0.88; }
    \\
    \\    .hero { background: var(--dark); padding: 80px 40px 64px; text-align: center; position: relative; overflow: hidden; }
    \\    .hero::before { content: ''; position: absolute; inset: 0; background: radial-gradient(ellipse 80% 60% at 50% 0%, rgba(232,130,26,0.08) 0%, transparent 70%); pointer-events: none; }
    \\    .hero-tag { font-family: var(--mono); font-size: 12px; font-weight: 600; color: var(--accent); letter-spacing: 0.12em; text-transform: uppercase; margin-bottom: 20px; }
    \\    .hero-title { font-family: var(--display); font-size: clamp(36px, 6vw, 64px); font-weight: 800; color: #fff; letter-spacing: -0.03em; line-height: 1.05; margin-bottom: 20px; }
    \\    .hero-title span { color: var(--accent); }
    \\    .hero-sub { font-size: 18px; color: rgba(255,255,255,0.55); max-width: 580px; margin: 0 auto 48px; line-height: 1.6; }
    \\    .stat-row { display: flex; justify-content: center; gap: 0; flex-wrap: wrap; max-width: 700px; margin: 0 auto 48px; border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; overflow: hidden; }
    \\    .stat { flex: 1; min-width: 140px; padding: 24px 20px; border-right: 1px solid rgba(255,255,255,0.08); text-align: center; }
    \\    .stat:last-child { border-right: none; }
    \\    .stat-val { font-family: var(--display); font-size: 28px; font-weight: 800; color: var(--accent); letter-spacing: -0.02em; }
    \\    .stat-label { font-size: 11px; font-weight: 600; color: rgba(255,255,255,0.35); text-transform: uppercase; letter-spacing: 0.08em; margin-top: 4px; }
    \\    .hero-actions { display: flex; gap: 14px; justify-content: center; flex-wrap: wrap; }
    \\    .btn { font-family: var(--display); font-size: 14px; font-weight: 700; padding: 12px 28px; border-radius: 6px; transition: opacity 0.15s, transform 0.15s; display: inline-flex; align-items: center; gap: 8px; }
    \\    .btn:hover { opacity: 0.88; transform: translateY(-1px); }
    \\    .btn-primary { background: var(--accent); color: #fff; }
    \\    .btn-outline { border: 1.5px solid rgba(255,255,255,0.2); color: rgba(255,255,255,0.8); }
    \\
    \\    .section { max-width: 1100px; margin: 0 auto; padding: 72px 40px; }
    \\    .section-header { margin-bottom: 40px; }
    \\    .section-tag { font-family: var(--mono); font-size: 11px; font-weight: 700; color: var(--accent); letter-spacing: 0.12em; text-transform: uppercase; margin-bottom: 12px; }
    \\    .section-title { font-family: var(--display); font-size: 32px; font-weight: 800; letter-spacing: -0.02em; color: var(--dark); }
    \\    .section-sub { font-size: 15px; color: var(--muted); margin-top: 8px; line-height: 1.6; }
    \\    .section-divider { border: none; border-top: 1px solid var(--border); margin: 0 40px; }
    \\
    \\    .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 20px; }
    \\    .card { background: #fff; border: 1px solid var(--border); border-radius: 10px; padding: 24px; transition: box-shadow 0.15s, transform 0.15s; }
    \\    .card:hover { box-shadow: 0 4px 20px rgba(0,0,0,0.08); transform: translateY(-2px); }
    \\    .card-title { font-family: var(--display); font-size: 15px; font-weight: 700; color: var(--dark); margin-bottom: 6px; }
    \\    .card-body { font-size: 13px; color: var(--muted); line-height: 1.6; }
    \\    .card-code { font-family: var(--mono); font-size: 11px; background: var(--bg2); border: 1px solid var(--border); border-radius: 6px; padding: 10px 12px; margin-top: 12px; color: #555; overflow-x: auto; white-space: pre; }
    \\    .card-tag { display: inline-block; font-family: var(--mono); font-size: 10px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; padding: 2px 8px; border-radius: 4px; margin-bottom: 10px; }
    \\    .tag-breaking { background: rgba(239,68,68,0.1); color: #dc2626; }
    \\    .tag-fix { background: rgba(34,197,94,0.1); color: #16a34a; }
    \\    .tag-new { background: rgba(59,130,246,0.1); color: #2563eb; }
    \\
    \\    .bug-list { display: flex; flex-direction: column; gap: 12px; }
    \\    .bug-item { background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 16px 20px; display: flex; gap: 16px; align-items: flex-start; }
    \\    .bug-num { font-family: var(--mono); font-size: 11px; font-weight: 700; color: var(--muted); min-width: 28px; padding-top: 2px; }
    \\    .bug-content { flex: 1; }
    \\    .bug-title { font-size: 14px; font-weight: 600; color: var(--dark); margin-bottom: 3px; }
    \\    .bug-desc { font-size: 13px; color: var(--muted); line-height: 1.5; }
    \\    .bug-pill { display: inline-block; font-family: var(--mono); font-size: 10px; font-weight: 600; padding: 1px 7px; border-radius: 4px; margin-left: 8px; background: var(--bg2); color: var(--muted); vertical-align: middle; }
    \\
    \\    .install-box { background: var(--dark); border-radius: 12px; padding: 48px 40px; text-align: center; }
    \\    .install-title { font-family: var(--display); font-size: 28px; font-weight: 800; color: #fff; margin-bottom: 8px; }
    \\    .install-sub { font-size: 15px; color: rgba(255,255,255,0.5); margin-bottom: 32px; }
    \\    .install-cmd { font-family: var(--mono); font-size: 15px; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; padding: 14px 24px; color: #fff; display: inline-block; margin-bottom: 24px; }
    \\    .install-cmd em { color: var(--accent); font-style: normal; }
    \\
    \\    footer { background: var(--dark2); border-top: 1px solid rgba(255,255,255,0.06); padding: 32px 40px; text-align: center; }
    \\    .footer-inner { max-width: 1100px; margin: 0 auto; }
    \\    .footer-text { font-size: 13px; color: rgba(255,255,255,0.25); }
    \\    .footer-text a { color: rgba(255,255,255,0.4); }
    \\    .footer-text a:hover { color: rgba(255,255,255,0.7); }
    \\
    \\    @media (max-width: 600px) {
    \\      .nav-inner { padding: 0 20px; }
    \\      .hero { padding: 56px 20px 48px; }
    \\      .section { padding: 48px 20px; }
    \\      .stat-row { flex-direction: column; }
    \\      .stat { border-right: none; border-bottom: 1px solid rgba(255,255,255,0.08); }
    \\      .stat:last-child { border-bottom: none; }
    \\      .install-box { padding: 32px 20px; }
    \\    }
    \\  </style>
    \\</head>
    \\<body>
    \\
    \\<nav>
    \\  <div class="nav-inner">
    \\    <a href="/" class="wordmark">Turbo<em>API</em></a>
    \\    <div class="nav-links">
    \\      <a href="/benchmarks">Benchmarks</a>
    \\      <a href="/docs">Docs</a>
    \\      <a href="/quickstart">Quickstart</a>
    \\      <a href="https://github.com/justrach/turboAPI" class="nav-cta">GitHub</a>
    \\    </div>
    \\  </div>
    \\</nav>
    \\
    \\<section class="hero">
    \\  <div class="hero-tag">Release Notes</div>
    \\  <h1 class="hero-title">TurboAPI <span>v1.0.28</span></h1>
    \\  <p class="hero-sub">Full Zig 0.16 compatibility, 21 bug fixes across the Python and Zig layers, native multipart parsing, structured logging, and 6 new fuzz targets.</p>
    \\  <div class="stat-row">
    \\    <div class="stat"><div class="stat-val">140k</div><div class="stat-label">req/s</div></div>
    \\    <div class="stat"><div class="stat-val">0.16ms</div><div class="stat-label">avg latency</div></div>
    \\    <div class="stat"><div class="stat-val">Zig 0.16</div><div class="stat-label">backend</div></div>
    \\    <div class="stat"><div class="stat-val">21</div><div class="stat-label">bugs fixed</div></div>
    \\  </div>
    \\  <div class="hero-actions">
    \\    <a href="#zig-migration" class="btn btn-primary">Zig 0.16 migration</a>
    \\    <a href="#bug-fixes" class="btn btn-outline">Bug fixes</a>
    \\  </div>
    \\</section>
    \\
    \\<hr class="section-divider">
    \\
    \\<section class="section" id="zig-migration">
    \\  <div class="section-header">
    \\    <div class="section-tag">Breaking changes</div>
    \\    <h2 class="section-title">Zig 0.16 migration</h2>
    \\    <p class="section-sub">Zig 0.16 removed several APIs that TurboAPI depended on. Here are the changes made to restore full compatibility.</p>
    \\  </div>
    \\  <div class="cards">
    \\    <div class="card">
    \\      <div class="card-tag tag-breaking">removed</div>
    \\      <div class="card-title">std.Thread.Mutex removed</div>
    \\      <div class="card-body">The high-level <code>std.Thread.Mutex</code> was dropped. Replaced with POSIX <code>pthread_mutex_t</code> throughout the cache layer.</div>
    \\      <div class="card-code">- lock: std.Thread.Mutex = .{},
    \\+ lock: std.c.pthread_mutex_t = std.c.PTHREAD_MUTEX_INITIALIZER,</div>
    \\    </div>
    \\    <div class="card">
    \\      <div class="card-tag tag-breaking">removed</div>
    \\      <div class="card-title">std.time.timestamp() removed</div>
    \\      <div class="card-body">Wall-clock timestamp generation was removed. Replaced with POSIX <code>clock_gettime(CLOCK_REALTIME)</code>.</div>
    \\      <div class="card-code">var ts: std.c.timespec = undefined;
    \\_ = std.c.clock_gettime(.REALTIME, &amp;ts);</div>
    \\    </div>
    \\    <div class="card">
    \\      <div class="card-tag tag-breaking">removed</div>
    \\      <div class="card-title">std.time.Timer removed</div>
    \\      <div class="card-body">Only <code>epoch</code> and constants remain in <code>std/time.zig</code>. Replaced with a <code>clock_gettime(CLOCK_MONOTONIC)</code> shim in the benchmark harness.</div>
    \\      <div class="card-code">const Timer = struct {
    \\    start_ns: u64,
    \\    fn start() Timer { ... }
    \\    fn read(self: Timer) u64 { ... }
    \\};</div>
    \\    </div>
    \\    <div class="card">
    \\      <div class="card-tag tag-breaking">changed</div>
    \\      <div class="card-title">testing.fuzz — Smith API</div>
    \\      <div class="card-body">Fuzz callbacks now receive <code>*std.testing.Smith</code> instead of <code>[]const u8</code>. Input is accessed via <code>smith.in</code>.</div>
    \\      <div class="card-code">fn fuzz_x(_: void, smith: *std.testing.Smith) !void {
    \\    const input = smith.in orelse return;
    \\}</div>
    \\    </div>
    \\    <div class="card">
    \\      <div class="card-tag tag-breaking">changed</div>
    \\      <div class="card-title">std.Io.Mutex — runtime init required</div>
    \\      <div class="card-body"><code>Io.Mutex.lockUncancelable</code> requires a valid <code>std.Io</code> context. Tests must initialise <code>runtime.threaded</code> and <code>runtime.io</code> before use.</div>
    \\      <div class="card-code">runtime.threaded = std.Io.Threaded.init(
    \\    std.heap.c_allocator, .{ .async_limit = .nothing });
    \\runtime.io = runtime.threaded.io();</div>
    \\    </div>
    \\    <div class="card">
    \\      <div class="card-tag tag-fix">fix</div>
    \\      <div class="card-title">link_libc explicit on Linux</div>
    \\      <div class="card-body">macOS auto-links libc but Linux CI failed with "dependency on libc must be explicitly specified". Added <code>link_libc = true</code> to <code>turboapi-core/build.zig</code>.</div>
    \\    </div>
    \\  </div>
    \\</section>
    \\
    \\<hr class="section-divider">
    \\
    \\<section class="section" id="bug-fixes">
    \\  <div class="section-header">
    \\    <div class="section-tag">Fixes</div>
    \\    <h2 class="section-title">21 bug fixes</h2>
    \\    <p class="section-sub">Bugs caught by fuzzing, static analysis, integration tests, and the Zig 0.16 migration.</p>
    \\  </div>
    \\  <div class="bug-list">
    \\    <div class="bug-item">
    \\      <div class="bug-num">#1</div>
    \\      <div class="bug-content">
    \\        <div class="bug-title">multipart.zig — Invalid free in debug allocator<span class="bug-pill">zig</span></div>
    \\        <div class="bug-desc"><code>ArrayListUnmanaged.items</code> is a capacity-sized view. Freeing it with slice length mismatches the allocation. Fixed with <code>toOwnedSlice()</code> at all 4 return sites.</div>
    \\      </div>
    \\    </div>
    \\    <div class="bug-item">
    \\      <div class="bug-num">#2</div>
    \\      <div class="bug-content">
    \\        <div class="bug-title">ASGI lifespan — wrong async protocol<span class="bug-pill">python</span></div>
    \\        <div class="bug-desc">Lifespan context manager was iterated with <code>__anext__</code> instead of <code>__aenter__</code>/<code>__aexit__</code>, causing silent startup failures.</div>
    \\      </div>
    \\    </div>
    \\    <div class="bug-item">
    \\      <div class="bug-num">#3</div>
    \\      <div class="bug-content">
    \\        <div class="bug-title">StaticFiles — path traversal bypass<span class="bug-pill">security</span></div>
    \\        <div class="bug-desc">Path normalisation in <code>get_file()</code> could be bypassed with <code>/../</code> sequences. Fixed with <code>os.path.realpath</code> + prefix check.</div>
    \\      </div>
    \\    </div>
    \\    <div class="bug-item">
    \\      <div class="bug-num">#4</div>
    \\      <div class="bug-content">
    \\        <div class="bug-title">responses.py — 4 bugs (tuple ABI, streaming, file, JSON)<span class="bug-pill">python</span></div>
    \\        <div class="bug-desc">Tuple packing mismatch between Python/Zig ABI; incorrect chunked encoding; unclosed file handles in FileResponse; double-encoding in JSONResponse.</div>
    \\      </div>
    \\    </div>
    \\    <div class="bug-item">
    \\      <div class="bug-num">#5</div>
    \\      <div class="bug-content">
    \\        <div class="bug-title">db.zig — GIL held during blocking I/O<span class="bug-pill">zig</span></div>
    \\        <div class="bug-desc">The Zig database helper held the Python GIL during blocking I/O, serialising all concurrent DB queries. Fixed with explicit <code>Py_BEGIN/END_ALLOW_THREADS</code>.</div>
    \\      </div>
    \\    </div>
    \\    <div class="bug-item">
    \\      <div class="bug-num">#6</div>
    \\      <div class="bug-content">
    \\        <div class="bug-title">dhi_validator.zig — 3 validation edge cases<span class="bug-pill">zig</span></div>
    \\        <div class="bug-desc">Integer overflow on large bounds; pattern validator not anchored (partial match accepted); <code>required</code> field check off-by-one.</div>
    \\      </div>
    \\    </div>
    \\    <div class="bug-item">
    \\      <div class="bug-num">#7</div>
    \\      <div class="bug-content">
    \\        <div class="bug-title">middleware.py — GZip double-compression<span class="bug-pill">python</span></div>
    \\        <div class="bug-desc">GZip middleware compressed already-compressed responses. Fixed with magic-byte detection before compressing.</div>
    \\      </div>
    \\    </div>
    \\    <div class="bug-item">
    \\      <div class="bug-num">#8</div>
    \\      <div class="bug-content">
    \\        <div class="bug-title">telemetry — malformed JSON hex escapes<span class="bug-pill">zig</span></div>
    \\        <div class="bug-desc">Control characters in log strings were emitted as raw bytes instead of <code>\uXXXX</code> JSON escapes, producing invalid JSON in structured log output.</div>
    \\      </div>
    \\    </div>
    \\    <div class="bug-item">
    \\      <div class="bug-num">#9</div>
    \\      <div class="bug-content">
    \\        <div class="bug-title">OpenAPI — Optional fields missing nullable<span class="bug-pill">python</span></div>
    \\        <div class="bug-desc"><code>Optional[T]</code> fields were emitted without <code>"nullable": true</code>, causing schema validators to reject valid null values.</div>
    \\      </div>
    \\    </div>
    \\    <div class="bug-item">
    \\      <div class="bug-num">#10</div>
    \\      <div class="bug-content">
    \\        <div class="bug-title">TestClient — UnboundLocalError on Python 3.14<span class="bug-pill">python</span></div>
    \\        <div class="bug-desc">Async TestClient raised <code>UnboundLocalError</code> on Python 3.14 due to a scoping change. Fixed with explicit variable initialisation before the try block.</div>
    \\      </div>
    \\    </div>
    \\    <div class="bug-item">
    \\      <div class="bug-num">#11–21</div>
    \\      <div class="bug-content">
    \\        <div class="bug-title">Zig 0.16 API removals — 11 call sites<span class="bug-pill">zig</span></div>
    \\        <div class="bug-desc">Thread.Mutex (cache), time.timestamp (http), time.Timer (bench), testing.fuzz callback signature (6 fuzz targets), Io.Mutex runtime init (concurrent test), link_libc on Linux CI.</div>
    \\      </div>
    \\    </div>
    \\  </div>
    \\</section>
    \\
    \\<hr class="section-divider">
    \\
    \\<section class="section" id="new-features">
    \\  <div class="section-header">
    \\    <div class="section-tag">New in v1.0.28</div>
    \\    <h2 class="section-title">New features</h2>
    \\  </div>
    \\  <div class="cards">
    \\    <div class="card">
    \\      <div class="card-tag tag-new">new</div>
    \\      <div class="card-title">Structured logging</div>
    \\      <div class="card-body">JSON-formatted request logs with timing, status, path, method, and request ID. Emitted from the Zig layer before the GIL is acquired, so logging never blocks request handling.</div>
    \\    </div>
    \\    <div class="card">
    \\      <div class="card-tag tag-new">new</div>
    \\      <div class="card-title">Native multipart parsing</div>
    \\      <div class="card-body">Multipart form data and URL-encoded bodies parsed entirely in Zig before Python is invoked. Zero-copy field access for small fields via <code>items</code> → <code>toOwnedSlice</code> fix.</div>
    \\    </div>
    \\    <div class="card">
    \\      <div class="card-tag tag-new">new</div>
    \\      <div class="card-title">6 fuzz targets</div>
    \\      <div class="card-body">Continuous fuzzing for router, HTTP parser, multipart, URL-encoded, DHI validator, and cache. Runs on every CI push via <code>zig build test --fuzz</code>.</div>
    \\    </div>
    \\    <div class="card">
    \\      <div class="card-tag tag-new">new</div>
    \\      <div class="card-title">Zig 0.16 migration docs</div>
    \\      <div class="card-body">Full write-up of every breaking API change and the replacement pattern used. See <code>docs/ZIG_0_16_MIGRATION.md</code> in the repo.</div>
    \\    </div>
    \\  </div>
    \\</section>
    \\
    \\<hr class="section-divider">
    \\
    \\<section class="section">
    \\  <div class="install-box">
    \\    <div class="install-title">Get v1.0.28</div>
    \\    <div class="install-sub">Requires Python 3.14t and Zig 0.16+</div>
    \\    <div class="install-cmd">uv pip install <em>turboapi==1.0.28</em></div>
    \\    <div class="hero-actions">
    \\      <a href="https://github.com/justrach/turboAPI/releases/tag/v1.0.28" class="btn btn-primary">Release on GitHub</a>
    \\      <a href="/docs" class="btn btn-outline">Read the docs</a>
    \\    </div>
    \\  </div>
    \\</section>
    \\
    \\<footer>
    \\  <div class="footer-inner">
    \\    <div class="footer-text">TurboAPI v1.0.28 &mdash; <a href="https://github.com/justrach/turboAPI">GitHub</a> &middot; <a href="/docs">Docs</a> &middot; <a href="/benchmarks">Benchmarks</a></div>
    \\  </div>
    \\</footer>
    \\
    \\</body>
    \\</html>
;
