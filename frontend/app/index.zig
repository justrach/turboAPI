const mer = @import("mer");

pub const meta: mer.Meta = .{
    .title = "TurboAPI — FastAPI-compatible. Zig HTTP core. 20x faster.",
    .description = "Drop-in FastAPI replacement with a Zig HTTP core. 20x faster, zero-copy responses, free-threading, per-worker tstate, dhi validation.",
};

pub const prerender = true;

pub fn render(req: mer.Request) mer.Response {
    _ = req;
    return .{ .status = .ok, .content_type = .html, .body = html };
}

const html =
    \\<!DOCTYPE html>
    \\<html lang="en">
    \\<head>
    \\  <meta charset="UTF-8">
    \\  <meta name="viewport" content="width=device-width, initial-scale=1.0">
    \\  <title>TurboAPI — FastAPI-compatible. Zig HTTP core. 20x faster.</title>
    \\  <link rel="preconnect" href="https://fonts.googleapis.com">
    \\  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    \\  <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    \\  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    \\  <style>
    \\    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    \\
    \\    :root {
    \\      --bg: #f9f8f6;
    \\      --bg2: #f2f0ec;
    \\      --bg3: #e9e5de;
    \\      --text: #0e0d0b;
    \\      --muted: #8a8478;
    \\      --border: #ddd9d2;
    \\      --accent: #e8821a;
    \\      --accent-dim: rgba(232,130,26,0.12);
    \\      --green: #2d7a3f;
    \\      --mono: 'JetBrains Mono', monospace;
    \\      --sans: 'Inter', sans-serif;
    \\      --display: 'Space Grotesk', sans-serif;
    \\    }
    \\
    \\    html { scroll-behavior: smooth; }
    \\    body {
    \\      background: var(--bg);
    \\      color: var(--text);
    \\      font-family: var(--sans);
    \\      min-height: 100vh;
    \\      line-height: 1.6;
    \\      overflow-x: hidden;
    \\    }
    \\    a { color: inherit; text-decoration: none; }
    \\
    \\    /* ── Layout ─────────────────────────────────────────── */
    \\    .wrap { max-width: 980px; margin: 0 auto; padding: 0 32px; }
    \\
    \\    /* ── Nav ────────────────────────────────────────────── */
    \\    nav {
    \\      position: sticky; top: 0; z-index: 100;
    \\      background: rgba(249,248,246,0.88);
    \\      backdrop-filter: blur(12px);
    \\      border-bottom: 1px solid var(--border);
    \\    }
    \\    .nav-inner {
    \\      display: flex; align-items: center;
    \\      justify-content: space-between;
    \\      height: 60px;
    \\    }
    \\    .wordmark {
    \\      font-family: var(--display);
    \\      font-size: 16px; font-weight: 800;
    \\      letter-spacing: -0.02em;
    \\    }
    \\    .wordmark em { font-style: normal; color: var(--accent); }
    \\    .nav-links { display: flex; gap: 32px; align-items: center; }
    \\    .nav-links a {
    \\      font-size: 13px; font-weight: 500;
    \\      color: var(--muted); letter-spacing: 0.01em;
    \\      transition: color 0.15s;
    \\    }
    \\    .nav-links a:hover { color: var(--text); }
    \\    .nav-cta {
    \\      font-family: var(--display);
    \\      font-size: 13px !important; font-weight: 700 !important;
    \\      color: #fff !important;
    \\      background: var(--accent);
    \\      padding: 8px 18px;
    \\      border-radius: 4px;
    \\      letter-spacing: 0.01em;
    \\    }
    \\    .nav-cta:hover { opacity: 0.88; }
    \\    .nav-burger {
    \\      display: none;
    \\      flex-direction: column; gap: 5px;
    \\      background: none; border: none; cursor: pointer; padding: 4px;
    \\    }
    \\    .nav-burger span {
    \\      display: block; width: 22px; height: 2px;
    \\      background: var(--text); border-radius: 2px;
    \\      transition: transform 0.2s, opacity 0.2s;
    \\    }
    \\    .nav-burger.open span:nth-child(1) { transform: translateY(7px) rotate(45deg); }
    \\    .nav-burger.open span:nth-child(2) { opacity: 0; }
    \\    .nav-burger.open span:nth-child(3) { transform: translateY(-7px) rotate(-45deg); }
    \\    @media (max-width: 640px) {
    \\      .nav-burger { display: flex; }
    \\      .nav-links {
    \\        display: none; flex-direction: column; gap: 0;
    \\        position: absolute; top: 60px; left: 0; right: 0;
    \\        background: rgba(249,248,246,0.97);
    \\        backdrop-filter: blur(12px);
    \\        border-bottom: 1px solid var(--border);
    \\        padding: 8px 0;
    \\      }
    \\      .nav-links.open { display: flex; }
    \\      .nav-links a { padding: 14px 24px; font-size: 15px; }
    \\      .nav-cta { margin: 8px 24px 12px; padding: 12px 20px; border-radius: 4px; text-align: center; }
    \\    }
    \\
    \\    /* ── Hero ───────────────────────────────────────────── */
    \\    .hero {
    \\      position: relative;
    \\      padding: 100px 0 80px;
    \\      overflow: hidden;
    \\    }
    \\    .hero-bg-num {
    \\      position: absolute;
    \\      top: 20px; right: 0;
    \\      font-family: var(--display);
    \\      font-size: clamp(120px, 16vw, 220px);
    \\      font-weight: 800;
    \\      color: var(--border);
    \\      opacity: 0.9;
    \\      line-height: 1;
    \\      pointer-events: none;
    \\      user-select: none;
    \\      letter-spacing: -0.05em;
    \\    }
    \\    .hero-label {
    \\      display: inline-flex; align-items: center; gap: 8px;
    \\      font-family: var(--mono);
    \\      font-size: 11px; font-weight: 500;
    \\      letter-spacing: 0.12em; text-transform: uppercase;
    \\      color: var(--accent);
    \\      margin-bottom: 28px;
    \\      opacity: 0; animation: fadeUp 0.6s 0.1s forwards;
    \\    }
    \\    .hero-label::before {
    \\      content: '';
    \\      display: inline-block;
    \\      width: 24px; height: 1px;
    \\      background: var(--accent);
    \\    }
    \\    .hero-title {
    \\      font-family: var(--display);
    \\      font-size: clamp(28px, 4vw, 46px);
    \\      font-weight: 700;
    \\      letter-spacing: -0.025em;
    \\      line-height: 1.15;
    \\      max-width: 580px;
    \\      margin-bottom: 24px;
    \\      opacity: 0; animation: fadeUp 0.7s 0.2s forwards;
    \\    }
    \\    .hero-title .accent { color: var(--accent); }
    \\    .hero-sub {
    \\      font-size: 16px;
    \\      color: var(--muted);
    \\      max-width: 480px;
    \\      line-height: 1.65;
    \\      margin-bottom: 40px;
    \\      opacity: 0; animation: fadeUp 0.7s 0.32s forwards;
    \\    }
    \\    .hero-actions {
    \\      display: flex; gap: 12px; align-items: center;
    \\      flex-wrap: wrap; margin-bottom: 40px;
    \\      opacity: 0; animation: fadeUp 0.7s 0.42s forwards;
    \\    }
    \\    .btn-primary {
    \\      font-family: var(--display);
    \\      font-size: 14px; font-weight: 700;
    \\      background: var(--accent); color: #fff;
    \\      padding: 13px 28px; border-radius: 4px;
    \\      letter-spacing: 0.01em;
    \\      transition: opacity 0.15s, transform 0.15s;
    \\    }
    \\    .btn-primary:hover { opacity: 0.88; transform: translateY(-1px); }
    \\    .btn-ghost {
    \\      font-size: 14px; font-weight: 500;
    \\      color: var(--muted);
    \\      border: 1px solid var(--border);
    \\      padding: 12px 24px; border-radius: 4px;
    \\      transition: color 0.15s, border-color 0.15s;
    \\    }
    \\    .btn-ghost:hover { color: var(--text); border-color: var(--text); }
    \\    .install-line {
    \\      display: inline-flex; align-items: center; gap: 12px;
    \\      font-family: var(--mono); font-size: 13px;
    \\      color: var(--muted);
    \\      opacity: 0; animation: fadeUp 0.7s 0.52s forwards;
    \\    }
    \\    .install-line span {
    \\      color: var(--accent); user-select: all;
    \\      cursor: copy;
    \\    }
    \\    .install-line::before { content: '$'; opacity: 0.4; }
    \\
    \\    /* ── Rule ───────────────────────────────────────────── */
    \\    .ruled {
    \\      border: none; border-top: 1px solid var(--border);
    \\      margin: 0;
    \\    }
    \\
    \\    /* ── Stats bar ──────────────────────────────────────── */
    \\    .stats-bar {
    \\      display: grid;
    \\      grid-template-columns: repeat(4, 1fr);
    \\      border-bottom: 1px solid var(--border);
    \\    }
    \\    @media (max-width: 600px) { .stats-bar { grid-template-columns: repeat(2,1fr); } }
    \\    .stat-cell {
    \\      padding: 36px 28px;
    \\      border-right: 1px solid var(--border);
    \\      position: relative;
    \\    }
    \\    .stat-cell:last-child { border-right: none; }
    \\    .stat-num {
    \\      font-family: var(--display);
    \\      font-size: clamp(32px, 4vw, 48px);
    \\      font-weight: 800;
    \\      letter-spacing: -0.04em;
    \\      color: var(--accent);
    \\      line-height: 1;
    \\      margin-bottom: 6px;
    \\    }
    \\    .stat-label {
    \\      font-size: 12px; font-weight: 500;
    \\      color: var(--muted);
    \\      letter-spacing: 0.04em;
    \\      text-transform: uppercase;
    \\    }
    \\
    \\    /* ── Instrument panel ───────────────────────────────── */
    \\    .panel-section { padding: 80px 0; }
    \\    .section-header {
    \\      display: flex; align-items: flex-end;
    \\      justify-content: space-between;
    \\      margin-bottom: 40px;
    \\      flex-wrap: wrap; gap: 16px;
    \\    }
    \\    .section-kicker {
    \\      font-family: var(--mono);
    \\      font-size: 10px; font-weight: 500;
    \\      letter-spacing: 0.14em; text-transform: uppercase;
    \\      color: var(--accent); margin-bottom: 8px;
    \\    }
    \\    .section-title {
    \\      font-family: var(--display);
    \\      font-size: clamp(22px, 3vw, 30px);
    \\      font-weight: 700; letter-spacing: -0.025em;
    \\      line-height: 1.15;
    \\    }
    \\    .chart-tabs {
    \\      display: flex; gap: 2px;
    \\      background: var(--bg3);
    \\      border-radius: 4px; padding: 3px;
    \\    }
    \\    .chart-tab {
    \\      font-family: var(--mono);
    \\      font-size: 11px; font-weight: 500;
    \\      letter-spacing: 0.04em;
    \\      padding: 7px 16px; border-radius: 3px;
    \\      cursor: pointer; border: none; background: none;
    \\      color: var(--muted); transition: all 0.15s;
    \\    }
    \\    .chart-tab.active {
    \\      background: var(--bg); color: var(--text);
    \\      box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    \\    }
    \\    .instrument {
    \\      background: var(--bg2);
    \\      border: 1px solid var(--border);
    \\      border-radius: 2px;
    \\      overflow: hidden;
    \\    }
    \\    .instrument-header {
    \\      display: flex; align-items: center; justify-content: space-between;
    \\      padding: 12px 20px;
    \\      border-bottom: 1px solid var(--border);
    \\      background: var(--bg3);
    \\    }
    \\    .instrument-dots { display: flex; gap: 6px; }
    \\    .instrument-dots span {
    \\      width: 8px; height: 8px; border-radius: 50%;
    \\      background: var(--border);
    \\    }
    \\    .instrument-dots span:first-child { background: #e8821a55; }
    \\    .instrument-label {
    \\      font-family: var(--mono);
    \\      font-size: 10px; color: var(--muted);
    \\      letter-spacing: 0.08em; text-transform: uppercase;
    \\    }
    \\    .instrument-body { padding: 28px; }
    \\    .chart-wrap { height: 300px; position: relative; }
    \\    .chart-legend {
    \\      display: flex; gap: 24px; margin-top: 20px;
    \\      flex-wrap: wrap;
    \\    }
    \\    .legend-item {
    \\      display: flex; align-items: center; gap: 7px;
    \\      font-family: var(--mono);
    \\      font-size: 11px; color: var(--muted);
    \\    }
    \\    .legend-dot {
    \\      width: 8px; height: 8px; border-radius: 1px;
    \\      flex-shrink: 0;
    \\    }
    \\    .legend-val {
    \\      font-weight: 500; color: var(--text);
    \\    }
    \\
    \\    /* ── Code diff ──────────────────────────────────────── */
    \\    .code-section { padding: 0 0 80px; }
    \\    .diff-block {
    \\      background: var(--bg2);
    \\      border: 1px solid var(--border);
    \\      border-radius: 2px;
    \\      overflow: hidden;
    \\      margin-top: 32px;
    \\    }
    \\    .diff-header {
    \\      background: var(--bg3);
    \\      border-bottom: 1px solid var(--border);
    \\      padding: 10px 20px;
    \\      display: flex; align-items: center; justify-content: space-between;
    \\    }
    \\    .diff-title {
    \\      font-family: var(--mono);
    \\      font-size: 11px; color: var(--muted);
    \\      letter-spacing: 0.06em;
    \\    }
    \\    .diff-badge {
    \\      font-family: var(--mono); font-size: 10px;
    \\      background: var(--accent-dim); color: var(--accent);
    \\      padding: 2px 8px; border-radius: 2px;
    \\      letter-spacing: 0.06em;
    \\    }
    \\    pre {
    \\      font-family: var(--mono);
    \\      font-size: 13px; line-height: 1.8;
    \\      padding: 24px 28px;
    \\      overflow-x: auto; color: var(--text);
    \\    }
    \\    .line { display: block; padding: 1px 8px; border-radius: 2px; }
    \\    .del { background: rgba(220,38,38,0.08); color: #c0392b; }
    \\    .add { background: rgba(45,122,63,0.08); color: #2d7a3f; }
    \\    .dim { color: var(--muted); }
    \\    .hl { color: var(--accent); }
    \\
    \\    /* ── Features ───────────────────────────────────────── */
    \\    .feat-section { padding: 0 0 80px; }
    \\    .feat-grid {
    \\      display: grid;
    \\      grid-template-columns: repeat(3, 1fr);
    \\      gap: 1px;
    \\      background: var(--border);
    \\      border: 1px solid var(--border);
    \\      border-radius: 2px;
    \\      overflow: hidden;
    \\      margin-top: 40px;
    \\    }
    \\    @media (max-width: 640px) { .feat-grid { grid-template-columns: 1fr; } }
    \\    .feat {
    \\      background: var(--bg);
    \\      padding: 32px 28px;
    \\      transition: background 0.2s;
    \\    }
    \\    .feat:hover { background: var(--bg2); }
    \\    .feat-num {
    \\      font-family: var(--mono);
    \\      font-size: 11px; color: var(--accent);
    \\      letter-spacing: 0.1em; margin-bottom: 16px;
    \\      opacity: 0.7;
    \\    }
    \\    .feat-title {
    \\      font-family: var(--display);
    \\      font-size: 16px; font-weight: 700;
    \\      letter-spacing: -0.02em;
    \\      margin-bottom: 10px;
    \\    }
    \\    .feat-desc {
    \\      font-size: 13px; color: var(--muted);
    \\      line-height: 1.65;
    \\    }
    \\
    \\    /* ── CTA ────────────────────────────────────────────── */
    \\    .cta-section { padding: 0 0 100px; }
    \\    .cta-inner {
    \\      border: 1px solid var(--border);
    \\      border-radius: 2px;
    \\      padding: 72px 56px;
    \\      display: flex; align-items: flex-start;
    \\      justify-content: space-between; gap: 48px;
    \\      flex-wrap: wrap;
    \\      position: relative; overflow: hidden;
    \\    }
    \\    .cta-inner::before {
    \\      content: '';
    \\      position: absolute; inset: 0;
    \\      background: linear-gradient(135deg, var(--accent-dim) 0%, transparent 60%);
    \\      pointer-events: none;
    \\    }
    \\    .cta-text {}
    \\    .cta-title {
    \\      font-family: var(--display);
    \\      font-size: clamp(28px, 4vw, 40px);
    \\      font-weight: 800; letter-spacing: -0.03em;
    \\      line-height: 1.1; margin-bottom: 12px;
    \\    }
    \\    .cta-sub { font-size: 14px; color: var(--muted); max-width: 340px; }
    \\    .cta-actions { display: flex; flex-direction: column; gap: 12px; justify-content: center; }
    \\
    \\    /* ── Footer ─────────────────────────────────────────── */
    \\    footer {
    \\      border-top: 1px solid var(--border);
    \\      padding: 32px 0;
    \\    }
    \\    .footer-inner {
    \\      display: flex; align-items: center;
    \\      justify-content: space-between; flex-wrap: wrap; gap: 16px;
    \\    }
    \\    .footer-word {
    \\      font-family: var(--display);
    \\      font-size: 13px; font-weight: 700; color: var(--muted);
    \\    }
    \\    .footer-word em { font-style: normal; color: var(--accent); }
    \\    .footer-links { display: flex; gap: 24px; }
    \\    .footer-links a {
    \\      font-size: 12px; color: var(--muted);
    \\      transition: color 0.15s;
    \\    }
    \\    .footer-links a:hover { color: var(--text); }
    \\
    \\    /* ── Animations ─────────────────────────────────────── */
    \\    @keyframes fadeUp {
    \\      from { opacity: 0; transform: translateY(16px); }
    \\      to   { opacity: 1; transform: translateY(0); }
    \\    }
    \\    .reveal {
    \\      opacity: 0; transform: translateY(20px);
    \\      transition: opacity 0.6s ease, transform 0.6s ease;
    \\    }
    \\    .reveal.in { opacity: 1; transform: none; }
    \\  </style>
    \\</head>
    \\<body>
    \\
    \\<!-- Nav -->
    \\<nav>
    \\  <div class="wrap nav-inner">
    \\    <a href="/" class="wordmark">Turbo<em>API</em></a>
    \\    <button class="nav-burger" id="burger" aria-label="Menu">
    \\      <span></span><span></span><span></span>
    \\    </button>
    \\    <div class="nav-links" id="nav-links">
    \\      <a href="/benchmarks">Benchmarks</a>
    \\      <a href="/docs">Docs</a>
    \\      <a href="https://github.com/justrach/turboAPI">GitHub</a>
    \\      <a href="/quickstart" class="nav-cta">Get started</a>
    \\    </div>
    \\  </div>
    \\</nav>
    \\
    \\<!-- Hero -->
    \\<section class="hero">
    \\  <div class="hero-bg-num">20×</div>
    \\  <div class="wrap">
    \\    <div class="hero-label">Alpha &nbsp;&middot;&nbsp; Experimental</div>
    \\    <h1 class="hero-title">
    \\      FastAPI-compatible.<br>
    \\      <span class="accent">Zig HTTP core.</span><br>
    \\      20x faster.
    \\    </h1>
    \\    <p class="hero-sub">
    \\      Drop-in replacement &middot; Zig-native validation &middot; Zero-copy responses &middot; Free-threading &middot; dhi models
    \\    </p>
    \\    <div class="hero-actions">
    \\      <a href="/quickstart" class="btn-primary">Get started</a>
    \\      <a href="/benchmarks" class="btn-ghost">View benchmarks</a>
    \\    </div>
    \\    <div class="install-line"><span>pip install turboapi</span></div>
    \\  </div>
    \\</section>
    \\
    \\<hr class="ruled">
    \\
    \\<!-- Stats -->
    \\<div class="stats-bar">
    \\  <div class="stat-cell">
    \\    <div class="stat-num">20×</div>
    \\    <div class="stat-label">Faster than FastAPI</div>
    \\  </div>
    \\  <div class="stat-cell">
    \\    <div class="stat-num">&lt;5ms</div>
    \\    <div class="stat-label">Cold start</div>
    \\  </div>
    \\  <div class="stat-cell">
    \\    <div class="stat-num">alpha</div>
    \\    <div class="stat-label">Experimental</div>
    \\  </div>
    \\  <div class="stat-cell">
    \\    <div class="stat-num">253+</div>
    \\    <div class="stat-label">Tests passing</div>
    \\  </div>
    \\</div>
    \\
    \\<!-- Chart / instrument panel -->
    \\<section class="panel-section">
    \\  <div class="wrap">
    \\    <div class="section-header reveal">
    \\      <div>
    \\        <div class="section-kicker">Performance</div>
    \\        <div class="section-title">Measured against<br>the field</div>
    \\      </div>
    \\      <div class="chart-tabs">
    \\        <button class="chart-tab active" onclick="switchChart('rps',this)">req/s</button>
    \\        <button class="chart-tab" onclick="switchChart('latency',this)">latency</button>
    \\        <button class="chart-tab" onclick="switchChart('cold',this)">cold start</button>
    \\        <button class="chart-tab" onclick="switchChart('mem',this)">memory</button>
    \\      </div>
    \\    </div>
    \\    <div class="instrument reveal">
    \\      <div class="instrument-header">
    \\        <div class="instrument-dots">
    \\          <span></span><span></span><span></span>
    \\        </div>
    \\        <div class="instrument-label" id="chartLabel">Requests per second &mdash; higher is better</div>
    \\        <div class="instrument-label">M3 Pro &middot; Python 3.14t &middot; wrk</div>
    \\      </div>
    \\      <div class="instrument-body">
    \\        <div class="chart-wrap"><canvas id="heroChart"></canvas></div>
    \\        <div class="chart-legend">
          \\          <div class="legend-item"><div class="legend-dot" style="background:#e8821a"></div>TurboAPI<span class="legend-val" id="v0">&nbsp;144,139</span></div>
    \\          <div class="legend-item"><div class="legend-dot" style="background:#c8c2ba"></div>Starlette<span class="legend-val" id="v1">&nbsp;9,201</span></div>
    \\          <div class="legend-item"><div class="legend-dot" style="background:#b5afa7"></div>FastAPI<span class="legend-val" id="v2">&nbsp;6,847</span></div>
    \\          <div class="legend-item"><div class="legend-dot" style="background:#a29c94"></div>Flask<span class="legend-val" id="v3">&nbsp;4,312</span></div>
    \\        </div>
    \\      </div>
    \\    </div>
    \\  </div>
    \\</section>
    \\
    \\<hr class="ruled">
    \\
    \\<!-- Code diff -->
    \\<section class="code-section">
    \\  <div class="wrap" style="padding-top:80px">
    \\    <div class="reveal">
    \\      <div class="section-kicker">Migration</div>
    \\      <div class="section-title">One line. That's it.</div>
    \\    </div>
    \\    <div class="diff-block reveal">
    \\      <div class="diff-header">
    \\        <span class="diff-title">main.py</span>
    \\        <span class="diff-badge">drop-in</span>
    \\      </div>
    \\      <pre><span class="line del">- from fastapi import FastAPI</span>
    \\<span class="line add">+ from turboapi import TurboAPI</span>
    \\<span class="line">&nbsp;</span>
    \\<span class="line dim">  # Everything else stays exactly the same</span>
    \\<span class="line"><span class="hl">app</span> = TurboAPI()</span>
    \\<span class="line">&nbsp;</span>
    \\<span class="line"><span class="dim">@app.get(</span><span class="hl">"/items/{item_id}"</span><span class="dim">)</span></span>
    \\<span class="line"><span class="dim">async def </span><span class="hl">read_item</span><span class="dim">(item_id: int):</span></span>
    \\<span class="line"><span class="dim">    return {</span><span class="hl">"item_id"</span><span class="dim">: item_id}</span></span></pre>
    \\    </div>
    \\  </div>
    \\</section>
    \\
    \\<!-- Features -->
    \\<section class="feat-section">
    \\  <div class="wrap">
    \\    <div class="reveal">
    \\      <div class="section-kicker">Capabilities</div>
    \\      <div class="section-title">Built for production<br>from the start</div>
    \\    </div>
    \\    <div class="feat-grid reveal">
    \\      <div class="feat">
    \\        <div class="feat-num">01</div>
    \\        <div class="feat-title">Zig HTTP server</div>
        \\        <p class="feat-desc">24-thread pool with keep-alive. Per-worker PyThreadState — zero per-request GIL lookup. Zero-copy response pipeline. Zig-side JSON parsing.</p>
    \\      </div>
    \\      <div class="feat">
    \\        <div class="feat-num">02</div>
    \\        <div class="feat-title">FastAPI-compatible</div>
    \\        <p class="feat-desc">Same route decorators, dependency injection, Pydantic models, and OpenAPI docs. No rewrite needed.</p>
    \\      </div>
    \\      <div class="feat">
    \\        <div class="feat-num">03</div>
    \\        <div class="feat-title">dhi validation</div>
    \\        <p class="feat-desc">Pydantic-style constraints compiled to native Zig. Validation happens before Python ever sees the data.</p>
    \\      </div>
    \\      <div class="feat">
    \\        <div class="feat-num">04</div>
    \\        <div class="feat-title">Free-threaded Python</div>
    \\        <p class="feat-desc">Python 3.14t free-threaded support. Pair with the Zig HTTP core to remove the GIL from your hot path entirely.</p>
    \\      </div>
    \\      <div class="feat">
    \\        <div class="feat-num">05</div>
    \\        <div class="feat-title">Full security stack</div>
    \\        <p class="feat-desc">OAuth2, Bearer tokens, API keys — the same security primitives from FastAPI, fully supported.</p>
    \\      </div>
    \\      <div class="feat">
    \\        <div class="feat-num">06</div>
    \\        <div class="feat-title">Native FFI handlers</div>
    \\        <p class="feat-desc">Mount handlers written in C or Zig directly. Zero Python overhead for your absolute hottest endpoints.</p>
    \\      </div>
    \\    </div>
    \\  </div>
    \\</section>
    \\
    \\<!-- CTA -->
    \\<section class="cta-section">
    \\  <div class="wrap">
    \\    <div class="cta-inner reveal">
    \\      <div class="cta-text">
    \\        <div class="cta-title">Ready to ship<br>faster APIs?</div>
        \\        <p class="cta-sub">Alpha &mdash; works and tested. 253+ tests passing. API surface may still change.</p>
    \\      </div>
    \\      <div class="cta-actions">
    \\        <a href="/quickstart" class="btn-primary">Quick start guide</a>
    \\        <a href="https://github.com/justrach/turboAPI" class="btn-ghost" style="text-align:center">View on GitHub</a>
    \\      </div>
    \\    </div>
    \\  </div>
    \\</section>
    \\
    \\<!-- Footer -->
    \\<footer>
    \\  <div class="wrap footer-inner">
    \\    <div class="footer-word">Turbo<em>API</em></div>
    \\    <div class="footer-links">
    \\      <a href="https://github.com/justrach/turboAPI">GitHub</a>
    \\      <a href="https://pypi.org/project/turboapi/">PyPI</a>
    \\      <a href="/docs">Docs</a>
    \\      <a href="/quickstart">Quick start</a>
    \\    </div>
    \\  </div>
    \\</footer>
    \\
    \\<script>
    \\// Chart
    \\const labels = ['TurboAPI', 'Starlette', 'FastAPI', 'Flask'];
    \\const barColors = ['#e8821a', '#c8c2ba', '#b5afa7', '#a29c94'];
    \\const chartData = {
    \\  rps:     { vals:[144139,9201,6847,4312],  unit:'req/s',  label:'Requests per second \u2014 higher is better',  fmt: v => v.toLocaleString() },
    \\  latency: { vals:[0.16,10.9,14.6,23.2],   unit:'ms',     label:'Avg latency ms \u2014 lower is better',        fmt: v => v+'ms' },
    \\  cold:    { vals:[5,600,800,400],          unit:'ms',     label:'Cold start ms \u2014 lower is better',         fmt: v => v+'ms' },
    \\  mem:     { vals:[12,58,72,38],            unit:'MB',     label:'Memory under load MB \u2014 lower is better',  fmt: v => v+'MB' },
    \\};
    \\let currentKey = 'rps';
    \\const chart = new Chart(document.getElementById('heroChart'), {
    \\  type: 'bar',
    \\  data: {
    \\    labels,
    \\    datasets: [{
    \\      data: chartData.rps.vals,
    \\      backgroundColor: barColors,
    \\      borderRadius: 3,
    \\      borderSkipped: false,
    \\      borderWidth: 0,
    \\    }],
    \\  },
    \\  options: {
    \\    responsive: true, maintainAspectRatio: false,
    \\    animation: { duration: 500, easing: 'easeOutQuart' },
    \\    plugins: {
    \\      legend: { display: false },
    \\      tooltip: {
    \\        backgroundColor: '#fff',
    \\        borderColor: '#ddd9d2', borderWidth: 1,
    \\        titleColor: '#0e0d0b', bodyColor: '#8a8478',
    \\        titleFont: { family: "'Syne', sans-serif", weight: '700', size: 13 },
    \\        bodyFont: { family: "'JetBrains Mono', monospace", size: 12 },
    \\        padding: 14,
    \\        callbacks: {
    \\          label: ctx => {
    \\            const d = chartData[currentKey];
    \\            return '  ' + d.fmt(ctx.parsed.y) + ' ' + d.unit;
    \\          },
    \\        },
    \\      },
    \\    },
    \\    scales: {
    \\      x: {
    \\        ticks: { color:'#8a8478', font:{ family:"'JetBrains Mono',monospace", size:12 } },
    \\        grid: { color:'#e9e5de' },
    \\      },
    \\      y: {
    \\        ticks: { color:'#8a8478', font:{ family:"'JetBrains Mono',monospace", size:11 } },
    \\        grid: { color:'#e9e5de' },
    \\      },
    \\    },
    \\  },
    \\});
    \\function switchChart(key, btn) {
    \\  document.querySelectorAll('.chart-tab').forEach(t => t.classList.remove('active'));
    \\  btn.classList.add('active');
    \\  currentKey = key;
    \\  const d = chartData[key];
    \\  chart.data.datasets[0].data = d.vals;
    \\  chart.update();
    \\  document.getElementById('chartLabel').textContent = d.label;
    \\  const ids = ['v0','v1','v2','v3'];
    \\  d.vals.forEach((v,i) => {
    \\    document.getElementById(ids[i]).textContent = '\u00a0' + d.fmt(v);
    \\  });
    \\}
    \\// Scroll reveal
    \\const obs = new IntersectionObserver(entries => {
    \\  entries.forEach(e => { if (e.isIntersecting) { e.target.classList.add('in'); obs.unobserve(e.target); } });
    \\}, { threshold: 0.1, rootMargin: '0px 0px -40px 0px' });
    \\document.querySelectorAll('.reveal').forEach(el => obs.observe(el));
    \\// Copy install
    \\document.querySelector('.install-line span').addEventListener('click', function() {
    \\  navigator.clipboard.writeText('pip install turboapi').catch(()=>{});
    \\  const orig = this.textContent;
    \\  this.textContent = 'copied!';
    \\  setTimeout(() => this.textContent = orig, 1500);
    \\});
    \\// Burger menu
    \\(function() {
    \\  var burger = document.getElementById('burger');
    \\  var links = document.getElementById('nav-links');
    \\  burger.addEventListener('click', function() {
    \\    burger.classList.toggle('open');
    \\    links.classList.toggle('open');
    \\  });
    \\  links.querySelectorAll('a').forEach(function(a) {
    \\    a.addEventListener('click', function() {
    \\      burger.classList.remove('open');
    \\      links.classList.remove('open');
    \\    });
    \\  });
    \\})();
    \\</script>
    \\</body>
    \\</html>
;
