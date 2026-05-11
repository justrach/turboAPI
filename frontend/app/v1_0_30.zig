const mer = @import("mer");
const framework_benchmarks = @import("framework_benchmarks");

pub const meta: mer.Meta = .{
    .title = "v1.0.30 - TurboAPI",
    .description = "TurboAPI v1.0.30: real WebSockets on the Zig HTTP core (RFC 6455), +30-75% hot-path perf vs v1.0.29, cross-platform verified on macOS arm64 + Linux x86_64.",
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
    \\  <title>v1.0.30 - TurboAPI</title>
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
    \\      --green: #22c55e; --blue: #3b82f6; --red: #ef4444;
    \\      --mono: 'JetBrains Mono', monospace;
    \\      --sans: 'Inter', sans-serif;
    \\      --display: 'Space Grotesk', sans-serif;
    \\    }
    \\    html { scroll-behavior: smooth; }
    \\    body { background: var(--bg); color: var(--text); font-family: var(--sans); min-height: 100vh; overflow-x: hidden; }
    \\    a { color: inherit; text-decoration: none; }
    \\    code { font-family: var(--mono); font-size: 0.92em; background: var(--bg2); border: 1px solid var(--border); border-radius: 4px; padding: 1px 5px; color: #5f5142; }
    \\    pre { font-family: var(--mono); font-size: 12.5px; background: var(--dark); color: rgba(255,255,255,0.86); border-radius: 8px; padding: 18px 20px; overflow-x: auto; line-height: 1.65; }
    \\    pre code { background: transparent; border: none; padding: 0; color: inherit; font-size: inherit; }
    \\
    \\    nav { position: sticky; top: 0; z-index: 100; background: rgba(14,13,11,0.92); backdrop-filter: blur(12px); border-bottom: 1px solid rgba(255,255,255,0.08); }
    \\    .nav-inner { max-width: 1100px; margin: 0 auto; padding: 0 40px; display: flex; align-items: center; justify-content: space-between; min-height: 60px; gap: 20px; }
    \\    .wordmark { font-family: var(--display); font-size: 16px; font-weight: 800; color: #fff; }
    \\    .wordmark em { font-style: normal; color: var(--accent); }
    \\    .nav-links { display: flex; gap: 28px; align-items: center; flex-wrap: wrap; }
    \\    .nav-links a { font-size: 13px; font-weight: 500; color: rgba(255,255,255,0.5); transition: color 0.15s; }
    \\    .nav-links a:hover { color: #fff; }
    \\    .nav-cta { font-family: var(--display); font-size: 13px !important; font-weight: 700 !important; color: #fff !important; background: var(--accent); padding: 8px 18px; border-radius: 4px; }
    \\
    \\    .hero { background: var(--dark); padding: 80px 40px 64px; text-align: center; position: relative; overflow: hidden; }
    \\    .hero::before { content: ''; position: absolute; inset: 0; background: radial-gradient(ellipse 80% 60% at 50% 0%, rgba(232,130,26,0.08) 0%, transparent 70%); pointer-events: none; }
    \\    .hero > * { position: relative; }
    \\    .hero-tag { font-family: var(--mono); font-size: 12px; font-weight: 700; color: var(--accent); letter-spacing: 0.12em; text-transform: uppercase; margin-bottom: 18px; }
    \\    .hero-title { font-family: var(--display); font-size: clamp(40px, 7vw, 76px); font-weight: 800; color: #fff; letter-spacing: -0.03em; line-height: 1.02; margin-bottom: 20px; }
    \\    .hero-title span { color: var(--accent); }
    \\    .hero-sub { font-size: 18px; color: rgba(255,255,255,0.58); max-width: 760px; margin: 0 auto 40px; line-height: 1.6; }
    \\    .stat-row { display: grid; grid-template-columns: repeat(4, 1fr); max-width: 840px; margin: 0 auto 42px; border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; overflow: hidden; }
    \\    .stat { padding: 24px 18px; border-right: 1px solid rgba(255,255,255,0.08); text-align: center; }
    \\    .stat:last-child { border-right: none; }
    \\    .stat-val { font-family: var(--display); font-size: 28px; font-weight: 800; color: var(--accent); letter-spacing: -0.02em; }
    \\    .stat-label { font-size: 11px; font-weight: 700; color: rgba(255,255,255,0.36); text-transform: uppercase; letter-spacing: 0.08em; margin-top: 4px; }
    \\    .hero-actions { display: flex; gap: 14px; justify-content: center; flex-wrap: wrap; }
    \\    .btn { font-family: var(--display); font-size: 14px; font-weight: 700; padding: 12px 26px; border-radius: 6px; transition: opacity 0.15s, transform 0.15s; display: inline-flex; align-items: center; justify-content: center; gap: 8px; }
    \\    .btn:hover { opacity: 0.88; transform: translateY(-1px); }
    \\    .btn-primary { background: var(--accent); color: #fff; }
    \\    .btn-outline { border: 1.5px solid rgba(255,255,255,0.22); color: rgba(255,255,255,0.84); }
    \\    .btn-soft { background: var(--bg2); border: 1px solid var(--border); color: var(--dark); }
    \\
    \\    .section { max-width: 1100px; margin: 0 auto; padding: 72px 40px; }
    \\    .section-tight { padding-top: 56px; padding-bottom: 56px; }
    \\    .section-header { margin-bottom: 36px; }
    \\    .section-tag { font-family: var(--mono); font-size: 11px; font-weight: 700; color: var(--accent); letter-spacing: 0.12em; text-transform: uppercase; margin-bottom: 12px; }
    \\    .section-title { font-family: var(--display); font-size: clamp(28px, 4vw, 40px); font-weight: 800; letter-spacing: -0.02em; color: var(--dark); }
    \\    .section-sub { font-size: 15px; color: var(--muted); margin-top: 8px; line-height: 1.7; max-width: 780px; }
    \\    .section-divider { border: none; border-top: 1px solid var(--border); max-width: 1100px; margin: 0 auto; }
    \\
    \\    .cards { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; }
    \\    .card { background: #fff; border: 1px solid var(--border); border-radius: 10px; padding: 22px; transition: border-color 0.15s, box-shadow 0.15s; }
    \\    .card:hover { border-color: var(--accent); box-shadow: 0 8px 24px rgba(232,130,26,0.07); }
    \\    .card-tag { display: inline-block; font-family: var(--mono); font-size: 10px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; padding: 3px 9px; border-radius: 99px; margin-bottom: 12px; }
    \\    .tag-new { background: rgba(34,197,94,0.13); color: #15803d; }
    \\    .tag-fast { background: var(--accent-dim); color: #9d5615; }
    \\    .tag-fix { background: rgba(59,130,246,0.13); color: #1e40af; }
    \\    .tag-pack { background: rgba(168,85,247,0.13); color: #6b21a8; }
    \\    .tag-doc { background: var(--bg2); color: var(--muted); }
    \\    .card-title { font-family: var(--display); font-size: 16px; font-weight: 800; margin-bottom: 8px; color: var(--dark); }
    \\    .card-body { font-size: 13.5px; color: #5f594f; line-height: 1.65; }
    \\
    \\    .compare-grid { display: grid; grid-template-columns: 1.4fr 1fr; gap: 18px; align-items: stretch; }
    \\    .table-card { background: #fff; border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
    \\    .table-title { font-family: var(--display); font-size: 16px; font-weight: 800; padding: 18px 22px; border-bottom: 1px solid var(--border); color: var(--dark); }
    \\    .table-wrap { overflow-x: auto; }
    \\    table { width: 100%; border-collapse: collapse; }
    \\    th, td { padding: 13px 16px; text-align: left; border-bottom: 1px solid var(--border); font-size: 13px; }
    \\    th { font-family: var(--mono); font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); background: var(--bg2); }
    \\    td { color: #5f594f; }
    \\    tr:last-child td { border-bottom: none; }
    \\    .num { font-family: var(--mono); white-space: nowrap; }
    \\    .win { color: #16a34a; font-weight: 700; }
    \\    .turbo { color: var(--accent); font-weight: 800; }
    \\    .note-card { background: var(--dark); color: rgba(255,255,255,0.64); border-radius: 10px; padding: 24px; font-size: 13px; line-height: 1.7; }
    \\    .note-card h3 { font-family: var(--display); font-size: 18px; color: #fff; margin-bottom: 10px; }
    \\    .note-card strong { color: #fff; }
    \\    .note-card a { color: var(--accent); }
    \\    .bars { display: flex; flex-direction: column; gap: 14px; margin-top: 18px; }
    \\    .bar-row { display: grid; grid-template-columns: 92px 1fr 74px; align-items: center; gap: 12px; }
    \\    .bar-name { font-family: var(--mono); font-size: 11px; color: rgba(255,255,255,0.45); text-align: right; }
    \\    .bar-name.turbo { color: #fff; }
    \\    .bar-track { height: 9px; background: rgba(255,255,255,0.12); border-radius: 99px; overflow: hidden; }
    \\    .bar-fill { height: 100%; border-radius: 99px; background: rgba(255,255,255,0.3); }
    \\    .bar-fill.turbo { background: var(--accent); }
    \\    .bar-num { font-family: var(--mono); font-size: 11px; color: rgba(255,255,255,0.5); }
    \\    .bar-num.turbo { color: var(--accent); font-weight: 700; }
    \\
    \\    .release-graphs { display: grid; gap: 20px; }
    \\    .graph-card { background: #fff; border: 1px solid var(--border); border-radius: 10px; padding: 24px; }
    \\    .graph-head { display: flex; justify-content: space-between; align-items: center; gap: 16px; margin-bottom: 20px; }
    \\    .graph-title { font-family: var(--display); font-size: 18px; font-weight: 800; color: var(--dark); letter-spacing: -0.01em; }
    \\    .graph-pill { font-family: var(--display); font-size: 13px; font-weight: 800; color: #7a4513; background: rgba(232,130,26,0.11); border: 1px solid rgba(232,130,26,0.28); border-radius: 99px; padding: 8px 14px; white-space: nowrap; }
    \\    .graph-pill.flat { color: #555; background: var(--bg2); border-color: var(--border); }
    \\    .graph-bars { display: grid; gap: 14px; }
    \\    .graph-row { display: grid; grid-template-columns: 116px 1fr 88px; gap: 14px; align-items: center; }
    \\    .graph-label { font-family: var(--mono); font-size: 13px; font-weight: 700; color: #777069; text-align: right; }
    \\    .graph-label.current { color: var(--dark); }
    \\    .graph-track { height: 44px; background: #f2f1ef; border-radius: 8px; overflow: hidden; }
    \\    .graph-fill { height: 100%; border-radius: 8px; }
    \\    .graph-fill.previous { background: #deddda; }
    \\    .graph-fill.current { background: linear-gradient(90deg, #f5df8d 0%, #e8821a 100%); }
    \\    .graph-value { font-family: var(--display); font-size: 16px; font-weight: 800; color: #33302b; white-space: nowrap; }
    \\    .graph-value.current { color: #9d5615; }
    \\    .graph-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 18px; }
    \\    .graph-note { font-size: 12px; color: var(--muted); line-height: 1.6; margin-top: 16px; }
    \\
    \\    .ws-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
    \\    .ws-card { background: #fff; border: 1px solid var(--border); border-radius: 10px; padding: 22px; }
    \\    .ws-card h3 { font-family: var(--display); font-size: 16px; font-weight: 800; color: var(--dark); margin-bottom: 14px; }
    \\    .ws-checklist { display: grid; gap: 8px; }
    \\    .ws-check { font-size: 13px; color: #5f594f; line-height: 1.55; display: flex; gap: 10px; align-items: flex-start; }
    \\    .ws-check::before { content: '✓'; color: #16a34a; font-weight: 800; flex-shrink: 0; margin-top: 1px; }
    \\    .ws-cross { font-size: 13px; color: #777069; line-height: 1.55; display: flex; gap: 10px; align-items: flex-start; }
    \\    .ws-cross::before { content: '○'; color: var(--muted); font-weight: 700; flex-shrink: 0; margin-top: 1px; }
    \\
    \\    .timeline { display: grid; gap: 12px; }
    \\    .change { background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 17px 20px; display: grid; grid-template-columns: 120px 1fr; gap: 18px; align-items: start; }
    \\    .change-kicker { font-family: var(--mono); font-size: 10px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: var(--accent); padding-top: 3px; }
    \\    .change-title { font-size: 14px; font-weight: 800; color: var(--dark); margin-bottom: 4px; }
    \\    .change-body { font-size: 13px; color: var(--muted); line-height: 1.6; }
    \\
    \\    .install-box { background: var(--dark); border-radius: 12px; padding: 42px 36px; text-align: center; }
    \\    .install-title { font-family: var(--display); font-size: 28px; font-weight: 800; color: #fff; margin-bottom: 8px; }
    \\    .install-sub { font-size: 15px; color: rgba(255,255,255,0.5); margin-bottom: 28px; }
    \\    .install-cmd { font-family: var(--mono); font-size: 14px; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; padding: 14px 20px; color: #fff; display: inline-block; margin-bottom: 22px; max-width: 100%; overflow-x: auto; white-space: nowrap; }
    \\    .install-cmd em { color: var(--accent); font-style: normal; }
    \\    footer { background: var(--dark2); border-top: 1px solid rgba(255,255,255,0.06); padding: 32px 40px; text-align: center; }
    \\    .footer-text { font-size: 13px; color: rgba(255,255,255,0.25); }
    \\    .footer-text a { color: rgba(255,255,255,0.4); }
    \\    .footer-text a:hover { color: rgba(255,255,255,0.7); }
    \\
    \\    @media (max-width: 780px) {
    \\      .nav-inner { padding: 14px 20px; align-items: flex-start; flex-direction: column; }
    \\      .nav-links { gap: 16px; }
    \\      .hero { padding: 56px 20px 48px; }
    \\      .section { padding: 48px 20px; }
    \\      .stat-row { grid-template-columns: repeat(2, 1fr); }
    \\      .stat:nth-child(2) { border-right: none; }
    \\      .stat:nth-child(1), .stat:nth-child(2) { border-bottom: 1px solid rgba(255,255,255,0.08); }
    \\      .compare-grid { grid-template-columns: 1fr; }
    \\      .graph-grid { grid-template-columns: 1fr; }
    \\      .change { grid-template-columns: 1fr; gap: 8px; }
    \\      .bar-row { grid-template-columns: 80px 1fr 64px; }
    \\      .graph-row { grid-template-columns: 86px 1fr 76px; }
    \\      .graph-head { align-items: flex-start; flex-direction: column; }
    \\      .ws-grid { grid-template-columns: 1fr; }
    \\    }
    \\    @media (max-width: 520px) {
    \\      .hero-title { font-size: 38px; }
    \\      .stat-row { grid-template-columns: 1fr; }
    \\      .stat { border-right: none; border-bottom: 1px solid rgba(255,255,255,0.08); }
    \\      .stat:last-child { border-bottom: none; }
    \\      .cards { grid-template-columns: 1fr; }
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
    \\  <h1 class="hero-title">TurboAPI <span>v1.0.30</span></h1>
    \\  <p class="hero-sub">Real WebSockets on the Zig HTTP core. RFC 6455 handshake + frames + masking + fragmentation + ping/pong + close handshake. Plus 30-75% hot-path throughput vs v1.0.29 from five focused dispatch-closure optimizations.</p>
    \\  <div class="stat-row">
    \\    <div class="stat"><div class="stat-val">RFC 6455</div><div class="stat-label">WebSockets</div></div>
    \\    <div class="stat"><div class="stat-val">+75%</div><div class="stat-label">POST /items vs v1.0.29</div></div>
    \\    <div class="stat"><div class="stat-val">23.5k</div><div class="stat-label">WS msgs/s loopback</div></div>
    \\    <div class="stat"><div class="stat-val">26/26</div><div class="stat-label">Zig tests passing</div></div>
    \\  </div>
    \\  <div class="hero-actions">
    \\    <a href="#websockets" class="btn btn-primary">WebSocket details</a>
    \\    <a href="#release-graphs" class="btn btn-outline">Perf graphs</a>
    \\    <a href="#install" class="btn btn-outline">Install</a>
    \\  </div>
    \\</section>
    \\
    \\<hr class="section-divider">
    \\
    \\<section class="section section-tight" id="websockets">
    \\  <div class="section-header">
    \\    <div class="section-tag">Headline feature</div>
    \\    <h2 class="section-title">Real WebSocket support, end-to-end</h2>
    \\    <p class="section-sub">Before v1.0.30 the Python <code>@app.websocket()</code> decorator was a stub backed by an in-memory <code>asyncio.Queue</code>; the Zig HTTP core had zero WebSocket code. This release wires it through. The same handler code now serves real wire traffic and the existing in-memory tests still pass unchanged. Closes <a href="https://github.com/justrach/turboAPI/issues/114" style="color:var(--accent)">#114</a>.</p>
    \\  </div>
    \\
    \\  <pre><code>from turboapi import TurboAPI
    \\from turboapi.websockets import WebSocket, WebSocketDisconnect
    \\
    \\app = TurboAPI()
    \\
    \\@app.websocket("/ws")
    \\async def handler(ws: WebSocket):
    \\    await ws.accept()
    \\    try:
    \\        while True:
    \\            msg = await ws.receive_text()
    \\            await ws.send_text(f"echo: {msg}")
    \\    except WebSocketDisconnect:
    \\        pass</code></pre>
    \\
    \\  <div class="ws-grid" style="margin-top:28px">
    \\    <div class="ws-card">
    \\      <h3>What's supported</h3>
    \\      <div class="ws-checklist">
    \\        <div class="ws-check">HTTP/1.1 Upgrade handshake with <code>Sec-WebSocket-Accept</code> validation</div>
    \\        <div class="ws-check">All RFC 6455 opcodes: text, binary, close, ping, pong, continuation</div>
    \\        <div class="ws-check">All three payload-length encodings (7-bit / 16-bit / 64-bit)</div>
    \\        <div class="ws-check">Server enforces client-frame masking per RFC §5.1</div>
    \\        <div class="ws-check">Auto-pong on ping; close handshake from either side</div>
    \\        <div class="ws-check">Fragmented client messages reassembled before delivery</div>
    \\        <div class="ws-check">FFI releases GIL around blocking socket I/O — free-threading friendly</div>
    \\        <div class="ws-check">In-memory <code>WebSocket()</code> mode preserved for unit tests</div>
    \\      </div>
    \\    </div>
    \\    <div class="ws-card">
    \\      <h3>Not yet supported</h3>
    \\      <div class="ws-checklist">
    \\        <div class="ws-cross">Path parameters on WS routes (<code>/ws/{room}</code>) — exact-match only for v1</div>
    \\        <div class="ws-cross"><code>permessage-deflate</code> compression extension</div>
    \\        <div class="ws-cross">Subprotocol negotiation</div>
    \\        <div class="ws-cross">Routes registered after <code>app.run()</code> (only at boot today)</div>
    \\      </div>
    \\    </div>
    \\  </div>
    \\
    \\  <div class="release-graphs" style="margin-top:28px">
    \\    <div class="graph-card">
    \\      <div class="graph-head"><div class="graph-title">WebSocket throughput - loopback, single connection, 5000 msg + 100 warmup</div><div class="graph-pill">RFC 6455</div></div>
    \\      <div class="graph-bars">
    \\        <div class="graph-row"><div class="graph-label">Linux x86_64 - /ws-echo (Zig only)</div><div class="graph-track"><div class="graph-fill current" style="width:100%"></div></div><div class="graph-value current">23,529/s</div></div>
    \\        <div class="graph-row"><div class="graph-label">Linux x86_64 - /ws-py (Python handler)</div><div class="graph-track"><div class="graph-fill current" style="width:79%"></div></div><div class="graph-value current">18,519/s</div></div>
    \\        <div class="graph-row"><div class="graph-label">macOS arm64 - /ws-echo</div><div class="graph-track"><div class="graph-fill previous" style="width:67%"></div></div><div class="graph-value">15,666/s</div></div>
    \\        <div class="graph-row"><div class="graph-label">macOS arm64 - /ws-py</div><div class="graph-track"><div class="graph-fill previous" style="width:65%"></div></div><div class="graph-value">15,295/s</div></div>
    \\      </div>
    \\      <div class="graph-note"><strong>Sub-millisecond p99 on both platforms.</strong> Linux p50/p99: <code>/ws-echo</code> 38µs/61µs, <code>/ws-py</code> 53µs/63µs. macOS p50/p99: <code>/ws-echo</code> 57µs/129µs, <code>/ws-py</code> 60µs/124µs. Linux numbers from an idle sandbox VM; macOS numbers from a dev box running editors/Chrome - the platform delta is environment noise, not a code path issue. For an LLM token-stream use case (~50 tok/s producer), the WS path provides &gt;300x headroom on either platform.</div>
    \\    </div>
    \\  </div>
    \\</section>
    \\
    \\<hr class="section-divider">
    \\
    \\<section class="section section-tight" id="release-graphs">
    \\  <div class="section-header">
    \\    <div class="section-tag">Release-over-release perf</div>
    \\    <h2 class="section-title">v1.0.30 is 30-75% faster than v1.0.29 on the hot path</h2>
    \\    <p class="section-sub">Five PRs landed targeted dispatch-closure optimizations: stripped wasted <code>{}</code> defaults in <code>kwargs.get("headers", {})</code>, cached <code>_returns_model</code> / <code>model_dump</code> detection at handler-creation time, and hoisted <code>parse_qs</code> / <code>HTTPException</code> imports out of fast-handler closures. Measured against <code>benchmarks/baseline.json</code> (committed 2026-04-27) using the same <code>benchmarks/bench_throughput.py</code> harness (TestClient, in-process) on the same hardware (Apple M-series, Python 3.14t free-threaded).</p>
    \\  </div>
    \\  <div class="release-graphs">
    \\    <div class="graph-card">
    \\      <div class="graph-head"><div class="graph-title">POST /items - biggest win</div><div class="graph-pill">+75%</div></div>
    \\      <div class="graph-bars">
    \\        <div class="graph-row"><div class="graph-label">v1.0.29</div><div class="graph-track"><div class="graph-fill previous" style="width:57%"></div></div><div class="graph-value">48,826/s</div></div>
    \\        <div class="graph-row"><div class="graph-label current">v1.0.30</div><div class="graph-track"><div class="graph-fill current" style="width:100%"></div></div><div class="graph-value current">85,687/s</div></div>
    \\      </div>
    \\      <div class="graph-note">POST routes pay for both header kwargs and body parsing; the <code>{}</code>-default fix in <a href="https://github.com/justrach/turboAPI/pull/155" style="color:var(--accent)">#155</a> + <a href="https://github.com/justrach/turboAPI/pull/159" style="color:var(--accent)">#159</a> compounds with the model-detection cache in <a href="https://github.com/justrach/turboAPI/pull/156" style="color:var(--accent)">#156</a> and <a href="https://github.com/justrach/turboAPI/pull/161" style="color:var(--accent)">#161</a>.</div>
    \\    </div>
    \\    <div class="graph-grid">
    \\      <div class="graph-card">
    \\        <div class="graph-head"><div class="graph-title">GET /</div><div class="graph-pill">+52%</div></div>
    \\        <div class="graph-bars">
    \\          <div class="graph-row"><div class="graph-label">v1.0.29</div><div class="graph-track"><div class="graph-fill previous" style="width:66%"></div></div><div class="graph-value">86,806/s</div></div>
    \\          <div class="graph-row"><div class="graph-label current">v1.0.30</div><div class="graph-track"><div class="graph-fill current" style="width:100%"></div></div><div class="graph-value current">132,167/s</div></div>
    \\        </div>
    \\      </div>
    \\      <div class="graph-card">
    \\        <div class="graph-head"><div class="graph-title">GET /items/{id}</div><div class="graph-pill flat">~flat</div></div>
    \\        <div class="graph-bars">
    \\          <div class="graph-row"><div class="graph-label">v1.0.29 baseline (~80k)</div><div class="graph-track"><div class="graph-fill previous" style="width:100%"></div></div><div class="graph-value">~80,000/s</div></div>
    \\          <div class="graph-row"><div class="graph-label current">v1.0.30</div><div class="graph-track"><div class="graph-fill current" style="width:97%"></div></div><div class="graph-value current">77,271/s</div></div>
    \\        </div>
    \\      </div>
    \\    </div>
    \\  </div>
    \\</section>
    \\
    \\<hr class="section-divider">
    \\
    \\<section class="section section-tight" id="changes">
    \\  <div class="section-header">
    \\    <div class="section-tag">What's changed</div>
    \\    <h2 class="section-title">The full release, grouped by impact</h2>
    \\    <p class="section-sub">One headline feature, five perf wins, one CI fix. No API breakage - <code>@app.websocket(...)</code> handlers that previously only worked in test mode now serve real traffic. In-memory <code>WebSocket()</code> instantiation still works for unit tests.</p>
    \\  </div>
    \\  <div class="cards">
    \\    <div class="card"><div class="card-tag tag-new">feature</div><div class="card-title">Real WebSocket on the Zig core (#167)</div><div class="card-body">RFC 6455 frame codec, HTTP upgrade handshake, per-connection lifecycle, Python FFI bridge. Closes <a href="https://github.com/justrach/turboAPI/issues/114" style="color:var(--accent)">#114</a>.</div></div>
    \\    <div class="card"><div class="card-tag tag-fast">perf</div><div class="card-title">Cache _returns_model across all handler kinds (#161)</div><div class="card-body">Extends the model-return detection cache from <code>fast_sync</code> to <code>pos_handler</code>, <code>async_pos_handler</code>, and <code>fast_model_handler</code> - avoids the per-request <code>hasattr</code> check.</div></div>
    \\    <div class="card"><div class="card-tag tag-fast">perf</div><div class="card-title">Cache model_dump detection at handler creation (#156)</div><div class="card-body">Moves the <code>hasattr(result, "model_dump")</code> check out of the request hot path into handler-construction time.</div></div>
    \\    <div class="card"><div class="card-tag tag-fast">perf</div><div class="card-title">Drop wasted {} defaults in headers kwargs (#155, #159)</div><div class="card-body"><code>kwargs.get("headers", {})</code> allocates a fresh dict on every miss. Switching to <code>or {}</code> with cached singletons trims that allocation across fast handler and enhanced_handler paths.</div></div>
    \\    <div class="card"><div class="card-tag tag-fast">perf</div><div class="card-title">Hoist parse_qs / HTTPException out of closures (#148)</div><div class="card-body">Each request was paying a <code>LOAD_GLOBAL</code> for these imports. Hoisted to module-level once at handler creation.</div></div>
    \\    <div class="card"><div class="card-tag tag-fast">perf</div><div class="card-title">Cache joined CORS header strings (#152)</div><div class="card-body">CORS middleware was joining <code>allow-methods</code> / <code>allow-headers</code> lists on every preflight. Moved to <code>__init__</code>, plus <code>max_age</code> as pre-stringified.</div></div>
    \\    <div class="card"><div class="card-tag tag-fix">fix</div><div class="card-title">Version-sync guard for CI (#154)</div><div class="card-body">The equality check failed on every PR since v1.0.28 because the staged version drifted from main. Switched to <code>&gt;=</code> so monotonic bumps pass.</div></div>
    \\  </div>
    \\</section>
    \\
    \\<hr class="section-divider">
    \\
    \\<section class="section" id="frameworks">
    \\  <div class="section-header">
    \\    <div class="section-tag">Framework comparison</div>
    \\    <h2 class="section-title">Proper framework comparison</h2>
    \\    <p class="section-sub">Same JSON handler shape from the NanoAPI benchmark notes. The checked-in source is <code>benchmarks/frameworks/latest.json</code>, refreshed by GitHub Actions.</p>
    \\  </div>
    \\  <div class="compare-grid">
    \\    <div class="table-card">
    \\      <div class="table-title">Equivalent JSON handlers, same runner profile</div>
    \\      <div class="table-wrap">
    \\        <table>
    \\          <thead><tr><th>Framework</th><th>Runtime</th><th><code>/</code></th><th><code>/users</code></th><th><code>/auth</code></th><th>Average</th><th>vs NanoAPI</th></tr></thead>
    \\          <tbody>
    \\
    ++ framework_benchmarks.table_rows ++
    \\
    \\          </tbody>
    \\        </table>
    \\      </div>
    \\    </div>
    \\    <div class="note-card">
    \\      <h3>Source of truth</h3>
    \\      <p><strong>Framework rows come from a benchmark artifact, not a hand-wavy Go estimate.</strong> The GitHub Action runs <code>benchmarks/frameworks/bench_frameworks.py</code> and writes both JSON and Markdown tables.</p>
    \\      <div class="bars">
    \\
    ++ framework_benchmarks.bar_rows ++
    \\
    \\      </div>
    \\      <p style="margin-top:18px">
    ++ framework_benchmarks.source_summary ++
    \\      </p>
    \\    </div>
    \\  </div>
    \\</section>
    \\
    \\<hr class="section-divider">
    \\
    \\<section class="section">
    \\  <div class="section-header">
    \\    <div class="section-tag">Release validation</div>
    \\    <h2 class="section-title">Cross-platform verified before tagging</h2>
    \\    <p class="section-sub">WebSocket implementation was verified end-to-end on both macOS arm64 (local dev) and Linux x86_64 (via the turbobox sandbox at <code>sandbox.trilok.ai</code>). The Linux run surfaced a <code>@memcpy</code> length-mismatch bug in a test fixture that macOS Zig 0.16 had elided - fixed in commit <code>d7f14b8</code> before tagging.</p>
    \\  </div>
    \\  <div class="compare-grid">
    \\    <div class="table-card">
    \\      <div class="table-title">Test results, both platforms</div>
    \\      <div class="table-wrap">
    \\        <table>
    \\          <thead><tr><th>Check</th><th>macOS arm64</th><th>Linux x86_64</th></tr></thead>
    \\          <tbody>
    \\            <tr><td><code>zig build test</code></td><td class="num turbo">26/26 pass</td><td class="num turbo">26/26 pass</td></tr>
    \\            <tr><td><code>pytest tests/test_websocket_e2e.py</code></td><td class="num turbo">10/10, ~90s</td><td class="num turbo">10/10, ~90s</td></tr>
    \\            <tr><td><code>pytest tests/test_fastapi_parity.py::TestWebSocket</code></td><td class="num turbo">4/4 pass</td><td class="num">-</td></tr>
    \\            <tr><td>Full pytest regression</td><td class="num turbo">404 pass, 0 regress</td><td class="num">-</td></tr>
    \\          </tbody>
    \\        </table>
    \\      </div>
    \\    </div>
    \\    <div class="note-card">
    \\      <h3>Wheels published</h3>
    \\      <p>Same matrix as v1.0.29 - macOS universal2 and manylinux x86_64 + sdist, all for free-threaded Python 3.14t. Regular GIL-enabled Python 3.14 is intentionally rejected at import time.</p>
    \\      <div class="bars">
    \\        <div class="bar-row"><div class="bar-name turbo">linux x86_64</div><div class="bar-track"><div class="bar-fill turbo" style="width:100%"></div></div><div class="bar-num turbo">.whl</div></div>
    \\        <div class="bar-row"><div class="bar-name turbo">macos arm64</div><div class="bar-track"><div class="bar-fill turbo" style="width:100%"></div></div><div class="bar-num turbo">.whl</div></div>
    \\        <div class="bar-row"><div class="bar-name">sdist</div><div class="bar-track"><div class="bar-fill" style="width:100%"></div></div><div class="bar-num">.tar.gz</div></div>
    \\      </div>
    \\      <p style="margin-top:18px">macOS wheel link-check verified: no <code>Python.framework</code> / <code>PythonT.framework</code> dependency baked in. <code>otool -L</code> shows only <code>@rpath/libturbonet.dylib</code> and <code>/usr/lib/libSystem.B.dylib</code>.</p>
    \\    </div>
    \\  </div>
    \\</section>
    \\
    \\<hr class="section-divider">
    \\
    \\<section class="section">
    \\  <div class="section-header">
    \\    <div class="section-tag">Release details</div>
    \\    <h2 class="section-title">Issues closed and what shipped</h2>
    \\  </div>
    \\  <div class="timeline">
    \\    <div class="change"><div class="change-kicker">closed</div><div><div class="change-title">#114 - zig runtime: real WebSocket support</div><div class="change-body">The Python <code>WebSocket</code> class was a queue-backed stub since day one. v1.0.30 wires it through to actual frame I/O on the Zig HTTP core, so <code>@app.websocket(...)</code> handlers register live routes and receive real socket traffic.</div></div></div>
    \\    <div class="change"><div class="change-kicker">verified</div><div><div class="change-title">Cross-platform on macOS + Linux</div><div class="change-body"><code>zig build test</code> green on both. <code>pytest tests/test_websocket_e2e.py</code> green on both (10/10, ~90s identical). Full pytest regression on macOS: 404 passed, 0 regressions. Linux verification via the turbobox sandbox surfaced a test-fixture bug Zig on Darwin had elided.</div></div></div>
    \\    <div class="change"><div class="change-kicker">perf</div><div><div class="change-title">+30-75% throughput vs v1.0.29</div><div class="change-body">TestClient throughput on the same hardware: <code>GET /</code> 86.8k → 132.2k r/s (+52%), <code>POST /items</code> 48.8k → 85.7k r/s (+75%). Wire-level wrk numbers still hold the ~140k req/s figure from the README.</div></div></div>
    \\    <div class="change"><div class="change-kicker">validated</div><div><div class="change-title">Release pipeline end-to-end</div><div class="change-body">Tag push triggered Build &amp; Publish on Ubuntu + macOS GitHub runners, smoke-imported each wheel in a clean venv, link-checked the macOS extension, published to PyPI, and created the GitHub Release.</div></div></div>
    \\  </div>
    \\</section>
    \\
    \\<hr class="section-divider">
    \\
    \\<section class="section" id="install">
    \\  <div class="install-box">
    \\    <div class="install-title">Install v1.0.30</div>
    \\    <div class="install-sub">Use Python 3.14t for the native backend and free-threaded runtime.</div>
    \\    <div class="install-cmd">python3.14t -m pip install <em>turboapi==1.0.30</em></div>
    \\    <div class="hero-actions">
    \\      <a href="https://github.com/justrach/turboAPI/releases/tag/v1.0.30" class="btn btn-primary">GitHub release</a>
    \\      <a href="https://pypi.org/project/turboapi/1.0.30/" class="btn btn-outline">PyPI</a>
    \\      <a href="/v1.0.29" class="btn btn-outline">v1.0.29 notes</a>
    \\      <a href="/benchmarks" class="btn btn-outline">Benchmarks</a>
    \\    </div>
    \\  </div>
    \\</section>
    \\
    \\<footer>
    \\  <div class="footer-text">TurboAPI v1.0.30 &mdash; <a href="https://github.com/justrach/turboAPI">GitHub</a> &middot; <a href="/docs">Docs</a> &middot; <a href="/benchmarks">Benchmarks</a> &middot; <a href="/v1.0.29">v1.0.29</a></div>
    \\</footer>
    \\
    \\</body>
    \\</html>
;
