const mer = @import("mer");

pub const meta: mer.Meta = .{
    .title = "HTTP Core",
    .description = "turboapi-core — shared Zig HTTP primitives. Router benchmark: 43.5M lookups/sec, faster than Go httprouter.",
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
    \\  <title>HTTP Core — TurboAPI</title>
    \\  <link rel="preconnect" href="https://fonts.googleapis.com">
    \\  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    \\  <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    \\  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    \\  <style>
    \\    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    \\    :root {
    \\      --bg: #f9f8f6; --bg2: #f2f0ec; --bg3: #e9e5de;
    \\      --dark: #0e0d0b; --dark2: #1a1916; --dark3: #252320;
    \\      --text: #0e0d0b; --muted: #8a8478; --border: #ddd9d2;
    \\      --accent: #e8821a; --accent-dim: rgba(232,130,26,0.15);
    \\      --zig: #f7a41d; --go: #00add8; --node: #68a063; --python: #3776ab;
    \\      --mono: 'JetBrains Mono', monospace;
    \\      --sans: 'Inter', sans-serif;
    \\      --display: 'Space Grotesk', sans-serif;
    \\    }
    \\    html { scroll-behavior: smooth; }
    \\    body { background: var(--dark); color: var(--text); font-family: var(--sans); min-height: 100vh; overflow-x: hidden; }
    \\    a { color: inherit; text-decoration: none; }
    \\
    \\    /* ── Nav ───────────────────────────────────── */
    \\    nav { position: sticky; top: 0; z-index: 100; background: rgba(14,13,11,0.9); backdrop-filter: blur(12px); border-bottom: 1px solid rgba(255,255,255,0.08); }
    \\    .nav-inner { max-width: 1100px; margin: 0 auto; padding: 0 40px; display: flex; align-items: center; justify-content: space-between; height: 60px; }
    \\    .wordmark { font-family: var(--display); font-size: 16px; font-weight: 800; letter-spacing: -0.02em; color: #fff; }
    \\    .wordmark em { font-style: normal; color: var(--accent); }
    \\    .nav-links { display: flex; gap: 32px; align-items: center; }
    \\    .nav-links a { font-size: 13px; font-weight: 500; color: rgba(255,255,255,0.5); letter-spacing: 0.01em; transition: color 0.15s; }
    \\    .nav-links a:hover { color: #fff; }
    \\    .nav-links a.active { color: #fff; }
    \\    .nav-cta { font-family: var(--display); font-size: 13px !important; font-weight: 700 !important; color: #fff !important; background: var(--accent); padding: 8px 18px; border-radius: 4px; }
    \\    .nav-cta:hover { opacity: 0.88; }
    \\    .nav-burger { display: none; flex-direction: column; gap: 5px; background: none; border: none; cursor: pointer; padding: 4px; }
    \\    .nav-burger span { display: block; width: 22px; height: 2px; background: #fff; border-radius: 2px; transition: transform 0.2s, opacity 0.2s; }
    \\    .nav-burger.open span:nth-child(1) { transform: translateY(7px) rotate(45deg); }
    \\    .nav-burger.open span:nth-child(2) { opacity: 0; }
    \\    .nav-burger.open span:nth-child(3) { transform: translateY(-7px) rotate(-45deg); }
    \\    @media (max-width: 640px) {
    \\      .nav-burger { display: flex; }
    \\      .nav-links { display: none; flex-direction: column; gap: 0; position: absolute; top: 60px; left: 0; right: 0; background: rgba(14,13,11,0.97); backdrop-filter: blur(12px); border-bottom: 1px solid rgba(255,255,255,0.08); padding: 8px 0; }
    \\      .nav-links.open { display: flex; }
    \\      .nav-links a { padding: 14px 24px; font-size: 15px; }
    \\      .nav-cta { margin: 8px 24px 12px; padding: 12px 20px; border-radius: 4px; text-align: center; }
    \\    }
    \\
    \\    /* ── Hero ──────────────────────────────────── */
    \\    .hero { background: var(--dark); padding: 80px 40px 0; max-width: 1100px; margin: 0 auto; }
    \\    .hero-label { font-family: var(--mono); font-size: 11px; font-weight: 500; letter-spacing: 0.14em; text-transform: uppercase; color: var(--accent); margin-bottom: 20px; display: flex; align-items: center; gap: 10px; }
    \\    .hero-label::before { content: ''; display: inline-block; width: 20px; height: 1px; background: var(--accent); }
    \\    .hero-headline { font-family: var(--display); font-size: clamp(44px, 7vw, 88px); font-weight: 800; letter-spacing: -0.04em; line-height: 0.95; color: #fff; margin-bottom: 16px; }
    \\    .hero-headline .hl { color: var(--accent); }
    \\    .hero-sub { font-family: var(--mono); font-size: 12px; color: rgba(255,255,255,0.35); letter-spacing: 0.04em; margin-bottom: 64px; }
    \\
    \\    /* ── Stat row ─────────────────────────────── */
    \\    .stat-row { display: grid; grid-template-columns: repeat(4,1fr); border-top: 1px solid rgba(255,255,255,0.08); }
    \\    @media (max-width: 700px) { .stat-row { grid-template-columns: repeat(2,1fr); } }
    \\    .stat-cell { padding: 32px 0 40px; border-right: 1px solid rgba(255,255,255,0.08); padding-right: 32px; }
    \\    .stat-cell:first-child { padding-left: 0; }
    \\    .stat-cell:last-child { border-right: none; }
    \\    .stat-val { font-family: var(--display); font-size: clamp(32px, 4vw, 52px); font-weight: 800; letter-spacing: -0.04em; color: #fff; line-height: 1; margin-bottom: 4px; }
    \\    .stat-val .unit { font-size: 0.45em; font-weight: 600; color: rgba(255,255,255,0.4); letter-spacing: 0; vertical-align: super; margin-left: 2px; }
    \\    .stat-label { font-family: var(--mono); font-size: 11px; color: rgba(255,255,255,0.4); letter-spacing: 0.08em; text-transform: uppercase; margin-bottom: 8px; }
    \\    .stat-delta { font-family: var(--mono); font-size: 11px; color: var(--accent); letter-spacing: 0.02em; }
    \\
    \\    /* ── Bars (cream) ────────────────────────── */
    \\    .bars-section { background: var(--bg); padding: 80px 40px; }
    \\    .bars-inner { max-width: 1100px; margin: 0 auto; }
    \\    .section-eyebrow { font-family: var(--mono); font-size: 11px; font-weight: 500; letter-spacing: 0.12em; text-transform: uppercase; color: var(--accent); margin-bottom: 10px; }
    \\    .section-heading { font-family: var(--display); font-size: clamp(22px, 3vw, 32px); font-weight: 800; letter-spacing: -0.025em; color: var(--dark); margin-bottom: 48px; }
    \\    .bar-row { display: grid; grid-template-columns: 180px 1fr 120px; align-items: center; gap: 16px; margin-bottom: 14px; }
    \\    .bar-name { font-family: var(--mono); font-size: 12px; color: var(--muted); text-align: right; letter-spacing: 0.02em; }
    \\    .bar-name.turbo { color: var(--dark); font-weight: 500; }
    \\    .bar-track { height: 10px; background: var(--bg3); border-radius: 99px; overflow: hidden; }
    \\    .bar-fill { height: 100%; border-radius: 99px; width: 0; transition: width 1s cubic-bezier(0.16,1,0.3,1); }
    \\    .bar-fill.zig { background: var(--zig); }
    \\    .bar-fill.go { background: var(--go); }
    \\    .bar-fill.node { background: var(--node); }
    \\    .bar-fill.python { background: var(--python); }
    \\    .bar-num { font-family: var(--mono); font-size: 12px; color: var(--muted); }
    \\    .bar-num.turbo { color: var(--accent); font-weight: 500; }
    \\    .bar-section-label { font-family: var(--mono); font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--muted); margin: 36px 0 16px 196px; }
    \\
    \\    /* ── Charts (dark) ────────────────────────── */
    \\    .charts-section { background: var(--dark2); padding: 80px 40px 100px; }
    \\    .charts-inner { max-width: 1100px; margin: 0 auto; }
    \\    .charts-section .section-heading { color: #fff; }
    \\    .chart-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 2px; margin-top: 2px; }
    \\    @media (max-width: 700px) { .chart-grid { grid-template-columns: 1fr; } }
    \\    .chart-card { background: var(--dark3); padding: 32px; }
    \\    .chart-card:first-child { border-radius: 8px 0 0 0; }
    \\    .chart-card:nth-child(2) { border-radius: 0 8px 0 0; }
    \\    .chart-card:nth-child(3) { border-radius: 0 0 0 8px; }
    \\    .chart-card:last-child { border-radius: 0 0 8px 0; }
    \\    .chart-card h2 { font-family: var(--display); font-size: 15px; font-weight: 700; color: #fff; margin-bottom: 4px; }
    \\    .chart-card .chart-sub { font-family: var(--mono); font-size: 11px; color: rgba(255,255,255,0.3); letter-spacing: 0.04em; margin-bottom: 24px; }
    \\    .chart-wrap { position: relative; height: 220px; }
    \\
    \\    /* ── What's inside ──────────────────────── */
    \\    .what-section { background: var(--bg); padding: 80px 40px; }
    \\    .what-inner { max-width: 1100px; margin: 0 auto; }
    \\    .what-grid { display: grid; grid-template-columns: repeat(3,1fr); gap: 2px; }
    \\    @media (max-width: 700px) { .what-grid { grid-template-columns: 1fr; } }
    \\    .what-card { background: #fff; padding: 32px; }
    \\    .what-card:first-child { border-radius: 8px 0 0 8px; }
    \\    .what-card:last-child { border-radius: 0 8px 8px 0; }
    \\    @media (max-width: 700px) { .what-card:first-child { border-radius: 8px 8px 0 0; } .what-card:last-child { border-radius: 0 0 8px 8px; } }
    \\    .what-card h3 { font-family: var(--display); font-size: 16px; font-weight: 700; color: var(--dark); margin-bottom: 8px; }
    \\    .what-card p { font-size: 13px; color: var(--muted); line-height: 1.6; }
    \\    .what-card code { font-family: var(--mono); font-size: 11px; background: var(--bg2); padding: 2px 6px; border-radius: 3px; }
    \\
    \\    /* ── Methodology + CTA ───────────────────── */
    \\    .method-section { background: var(--dark); padding: 0 40px 100px; }
    \\    .method-inner { max-width: 1100px; margin: 0 auto; border-top: 1px solid rgba(255,255,255,0.08); padding-top: 48px; display: flex; gap: 60px; align-items: flex-start; }
    \\    @media (max-width: 700px) { .method-inner { flex-direction: column; gap: 32px; } }
    \\    .method-text { flex: 1; font-size: 13px; color: rgba(255,255,255,0.4); line-height: 1.8; font-family: var(--mono); }
    \\    .method-text strong { color: rgba(255,255,255,0.7); font-weight: 500; }
    \\    .method-text a { color: var(--accent); }
    \\    .method-ctas { display: flex; flex-direction: column; gap: 12px; flex-shrink: 0; }
    \\    .btn { display: inline-flex; align-items: center; justify-content: center; font-family: var(--display); font-size: 14px; font-weight: 700; padding: 13px 28px; border-radius: 4px; background: var(--accent); color: #fff; transition: opacity 0.15s, transform 0.15s; white-space: nowrap; }
    \\    .btn:hover { opacity: 0.88; transform: translateY(-1px); }
    \\    .btn-ghost { background: transparent; border: 1px solid rgba(255,255,255,0.15); color: rgba(255,255,255,0.6); font-weight: 500; }
    \\    .btn-ghost:hover { border-color: rgba(255,255,255,0.4); color: #fff; transform: none; }
    \\    .layout-footer { padding: 20px 40px; border-top: 1px solid rgba(255,255,255,0.06); font-size: 11px; color: rgba(255,255,255,0.2); text-align: center; font-family: var(--mono); letter-spacing: 0.04em; background: var(--dark); }
    \\    .layout-footer a { color: rgba(255,255,255,0.2); }
    \\    .layout-footer a:hover { color: rgba(255,255,255,0.5); }
    \\  </style>
    \\</head>
    \\<body>
    \\
    \\<!-- Nav -->
    \\<nav>
    \\  <div class="nav-inner">
    \\    <a href="/" class="wordmark">Turbo<em>API</em></a>
    \\    <button class="nav-burger" id="burger" aria-label="Menu">
    \\      <span></span><span></span><span></span>
    \\    </button>
    \\    <div class="nav-links" id="nav-links">
    \\      <a href="/benchmarks">Benchmarks</a>
    \\      <a href="/httpcore" class="active">HTTP Core</a>
    \\      <a href="/docs">Docs</a>
    \\      <a href="https://github.com/justrach/turboapi-core">GitHub</a>
    \\      <a href="/quickstart" class="nav-cta">Get started</a>
    \\    </div>
    \\  </div>
    \\</nav>
    \\
    \\<!-- Hero -->
    \\<div style="background:var(--dark);">
    \\  <div class="hero">
    \\    <div class="hero-label">turboapi-core</div>
    \\    <div class="hero-headline">
    \\      <span class="hl">43.5M</span> route<br>lookups/sec.
    \\    </div>
    \\    <div class="hero-sub">Shared Zig HTTP core &nbsp;&middot;&nbsp; Zero dependencies &nbsp;&middot;&nbsp; Faster than Go httprouter</div>
    \\    <div class="stat-row">
    \\      <div class="stat-cell">
    \\        <div class="stat-label">Mixed workload</div>
    \\        <div class="stat-val">43.5<span class="unit">M/s</span></div>
    \\        <div class="stat-delta">23ns per lookup</div>
    \\      </div>
    \\      <div class="stat-cell" style="padding-left:32px;">
    \\        <div class="stat-label">Static route</div>
    \\        <div class="stat-val">100<span class="unit">M/s</span></div>
    \\        <div class="stat-delta">10ns &middot; GET /health</div>
    \\      </div>
    \\      <div class="stat-cell" style="padding-left:32px;">
    \\        <div class="stat-label">Param route</div>
    \\        <div class="stat-val">52<span class="unit">M/s</span></div>
    \\        <div class="stat-delta">19ns &middot; /users/{id}</div>
    \\      </div>
    \\      <div class="stat-cell" style="padding-left:32px;">
    \\        <div class="stat-label">Wildcard route</div>
    \\        <div class="stat-val">15.6<span class="unit">M/s</span></div>
    \\        <div class="stat-delta">64ns &middot; /static/*path</div>
    \\      </div>
    \\    </div>
    \\  </div>
    \\</div>
    \\
    \\<!-- Cross-language comparison bars -->
    \\<div class="bars-section">
    \\  <div class="bars-inner">
    \\    <div class="section-eyebrow">Router showdown</div>
    \\    <div class="section-heading">Lookups per second &mdash; same routes, same machine</div>
    \\    <div class="bar-section-label">Higher is better &middot; M3 Pro &middot; 16 routes &middot; 5M iterations</div>
    \\    <div class="bar-row">
    \\      <div class="bar-name turbo">turboapi-core (Zig)</div>
    \\      <div class="bar-track"><div class="bar-fill zig" data-pct="100"></div></div>
    \\      <div class="bar-num turbo">43.5M/s &middot; 23ns</div>
    \\    </div>
    \\    <div class="bar-row">
    \\      <div class="bar-name">Go httprouter</div>
    \\      <div class="bar-track"><div class="bar-fill go" data-pct="92"></div></div>
    \\      <div class="bar-num">40M/s &middot; 25ns</div>
    \\    </div>
    \\    <div class="bar-row">
    \\      <div class="bar-name">find-my-way (Node)</div>
    \\      <div class="bar-track"><div class="bar-fill node" data-pct="26"></div></div>
    \\      <div class="bar-num">10.5M/s &middot; 95ns</div>
    \\    </div>
    \\    <div class="bar-row">
    \\      <div class="bar-name">Starlette (Python)</div>
    \\      <div class="bar-track"><div class="bar-fill python" data-pct="10"></div></div>
    \\      <div class="bar-num">4M/s &middot; 249ns</div>
    \\    </div>
    \\  </div>
    \\</div>
    \\
    \\<!-- Charts -->
    \\<div class="charts-section">
    \\  <div class="charts-inner">
    \\    <div class="section-eyebrow">Route type breakdown</div>
    \\    <div class="section-heading">Performance by route pattern</div>
    \\    <div class="chart-grid">
    \\      <div class="chart-card">
    \\        <h2>Lookups / second</h2>
    \\        <p class="chart-sub">Mixed workload &middot; higher is better</p>
    \\        <div class="chart-wrap"><canvas id="lpsChart"></canvas></div>
    \\      </div>
    \\      <div class="chart-card">
    \\        <h2>Nanoseconds / lookup</h2>
    \\        <p class="chart-sub">Mixed workload &middot; lower is better</p>
    \\        <div class="chart-wrap"><canvas id="nsChart"></canvas></div>
    \\      </div>
    \\      <div class="chart-card">
    \\        <h2>By route type (turboapi-core)</h2>
    \\        <p class="chart-sub">Millions of lookups/sec &middot; higher is better</p>
    \\        <div class="chart-wrap"><canvas id="typeChart"></canvas></div>
    \\      </div>
    \\      <div class="chart-card">
    \\        <h2>Latency by route type</h2>
    \\        <p class="chart-sub">Nanoseconds &middot; lower is better</p>
    \\        <div class="chart-wrap"><canvas id="typeNsChart"></canvas></div>
    \\      </div>
    \\    </div>
    \\  </div>
    \\</div>
    \\
    \\<!-- What's inside -->
    \\<div class="what-section">
    \\  <div class="what-inner">
    \\    <div class="section-eyebrow">What's inside</div>
    \\    <div class="section-heading">turboapi-core modules</div>
    \\    <div class="what-grid">
    \\      <div class="what-card">
    \\        <h3>Radix Trie Router</h3>
    \\        <p>Method-aware routing with <code>{param}</code> and <code>*wildcard</code> support. Zero-alloc param extraction via fixed stack array. Fuzz-tested with adversarial inputs. 530 lines.</p>
    \\      </div>
    \\      <div class="what-card">
    \\        <h3>HTTP Utilities</h3>
    \\        <p><code>percentDecode</code>, <code>queryStringGet</code>, <code>statusText</code>, <code>formatHttpDate</code>. Pure functions, no allocations, no dependencies. Battle-tested at 134k req/s.</p>
    \\      </div>
    \\      <div class="what-card">
    \\        <h3>Bounded Cache</h3>
    \\        <p>Thread-safe <code>BoundedCache(V)</code> with mutex and configurable max entries. Generic over value type. Used for response caching in turboAPI.</p>
    \\      </div>
    \\    </div>
    \\  </div>
    \\</div>
    \\
    \\<!-- Methodology + CTA -->
    \\<div class="method-section">
    \\  <div class="method-inner">
    \\    <div class="method-text">
    \\      <strong>Methodology</strong><br><br>
    \\      All benchmarks run on Apple M3 Pro.<br>
    \\      16 routes registered (static, param, multi-param, wildcard).<br>
    \\      13 lookup patterns per iteration, 5M iterations.<br>
    \\      ReleaseFast for Zig, -O2 for Go, V8 JIT for Node, CPython 3.14 for Python.<br>
    \\      Pure routing — no HTTP I/O, no serialization, no framework overhead.<br><br>
    \\      <a href="https://github.com/justrach/turboapi-core">View source on GitHub &rarr;</a><br>
    \\      <a href="https://github.com/justrach/turboapi-core/issues/1">Optimization roadmap &rarr;</a>
    \\    </div>
    \\    <div class="method-ctas">
    \\      <a href="https://github.com/justrach/turboapi-core" class="btn">turboapi-core</a>
    \\      <a href="/benchmarks" class="btn btn-ghost">HTTP benchmarks</a>
    \\      <a href="https://github.com/justrach/turboAPI" class="btn btn-ghost">turboAPI</a>
    \\      <a href="https://github.com/justrach/merjs" class="btn btn-ghost">merjs</a>
    \\    </div>
    \\  </div>
    \\</div>
    \\
    \\<footer class="layout-footer">
    \\  turboapi-core &mdash; shared Zig HTTP primitives &middot; <a href="https://github.com/justrach/turboapi-core">GitHub</a> &middot; <a href="https://github.com/justrach/turboAPI">turboAPI</a> &middot; <a href="https://github.com/justrach/merjs">merjs</a>
    \\</footer>
    \\
    \\<script>
    \\// Animate bars
    \\window.addEventListener('load', function() {
    \\  document.querySelectorAll('.bar-fill').forEach(function(el) {
    \\    el.style.width = el.dataset.pct + '%';
    \\  });
    \\});
    \\// Chart config
    \\const routerLabels = ['turboapi-core', 'Go httprouter', 'find-my-way', 'Starlette'];
    \\const routerColors = ['#f7a41d', '#00add8', '#68a063', '#3776ab'];
    \\const typeLabels = ['Static', 'Deep static', '1-param', '2-param', 'Wildcard', 'Miss'];
    \\const typeColor = '#f7a41d';
    \\const opts = (unit, rev) => ({
    \\  indexAxis: 'y',
    \\  responsive: true, maintainAspectRatio: false,
    \\  animation: { duration: 800, easing: 'easeOutQuart' },
    \\  plugins: {
    \\    legend: { display: false },
    \\    tooltip: {
    \\      backgroundColor: '#1a1916', borderColor: 'rgba(255,255,255,0.1)', borderWidth: 1,
    \\      titleColor: '#fff', bodyColor: 'rgba(255,255,255,0.5)', padding: 12,
    \\      callbacks: { label: ctx => ` ${ctx.parsed.x.toLocaleString()} ${unit}` },
    \\    },
    \\  },
    \\  scales: {
    \\    y: { ticks: { color: 'rgba(255,255,255,0.3)', font: { size: 11, family: "'JetBrains Mono'" } }, grid: { display: false } },
    \\    x: { reverse: rev, ticks: { color: 'rgba(255,255,255,0.3)', font: { size: 11, family: "'JetBrains Mono'" } }, grid: { color: 'rgba(255,255,255,0.04)' } },
    \\  },
    \\});
    \\function hbar(id, labels, data, colors, unit, rev) {
    \\  new Chart(document.getElementById(id), {
    \\    type: 'bar',
    \\    data: { labels, datasets: [{ data, backgroundColor: colors, borderRadius: 4, borderSkipped: false }] },
    \\    options: opts(unit, rev || false),
    \\  });
    \\}
    \\hbar('lpsChart', routerLabels, [43.5, 40, 10.5, 4], routerColors, 'M lookups/s');
    \\hbar('nsChart', routerLabels, [23, 25, 95, 249], routerColors, 'ns/op', true);
    \\hbar('typeChart', typeLabels, [100, 91, 52, 34, 15.6, 100], Array(6).fill(typeColor), 'M/s');
    \\hbar('typeNsChart', typeLabels, [10, 11, 19, 29, 64, 10], Array(6).fill(typeColor), 'ns', true);
    \\// Burger
    \\(function() {
    \\  var burger = document.getElementById('burger');
    \\  var links = document.getElementById('nav-links');
    \\  burger.addEventListener('click', function() { burger.classList.toggle('open'); links.classList.toggle('open'); });
    \\  links.querySelectorAll('a').forEach(function(a) { a.addEventListener('click', function() { burger.classList.remove('open'); links.classList.remove('open'); }); });
    \\})();
    \\</script>
    \\</body>
    \\</html>
;
