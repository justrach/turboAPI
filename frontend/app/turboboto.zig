const mer = @import("mer");

pub const meta: mer.Meta = .{
    .title = "TurboBoto",
    .description = "Drop-in boto3 replacement powered by Zig. 115x faster S3 with TurboAPI, 1.19x faster standalone.",
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
    \\  <title>TurboBoto — Zig-accelerated boto3</title>
    \\  <link rel="preconnect" href="https://fonts.googleapis.com">
    \\  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    \\  <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    \\  <style>
    \\    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    \\    :root {
    \\      --bg: #fafaf9; --bg2: #f5f0eb; --bg3: #ebe4db;
    \\      --text: #1a1a1a; --muted: #6b7280; --border: #e5e0d8;
    \\      --orange: #ff9900; --orange-dim: rgba(255,153,0,0.10); --orange-border: rgba(255,153,0,0.30);
    \\      --orange-dark: #e88a00; --zig: #f7a41d;
    \\      --green: #16a34a; --green-dim: rgba(22,163,74,0.08);
    \\      --mono: 'JetBrains Mono', monospace;
    \\      --sans: 'Inter', sans-serif;
    \\      --display: 'Space Grotesk', sans-serif;
    \\    }
    \\    body { background: var(--bg); color: var(--text); font-family: var(--sans); }
    \\    a { color: var(--orange-dark); text-decoration: none; }
    \\    a:hover { text-decoration: underline; }
    \\    nav { position: sticky; top: 0; z-index: 100; background: rgba(250,250,249,0.92); backdrop-filter: blur(12px); border-bottom: 1px solid var(--border); }
    \\    .nav-inner { max-width: 1100px; margin: 0 auto; padding: 0 40px; display: flex; align-items: center; justify-content: space-between; height: 60px; }
    \\    .wordmark { font-family: var(--display); font-size: 16px; font-weight: 800; color: var(--text); }
    \\    .wordmark em { font-style: normal; color: var(--orange); }
    \\    .nav-links { display: flex; gap: 32px; align-items: center; }
    \\    .nav-links a { font-size: 13px; font-weight: 500; color: var(--muted); text-decoration: none; }
    \\    .nav-links a:hover { color: var(--text); }
    \\    .nav-cta { color: #fff !important; background: var(--orange); padding: 8px 18px; border-radius: 4px; font-family: var(--display); font-weight: 700 !important; }
    \\    .hero { padding: 80px 40px 60px; text-align: center; }
    \\    .hero h1 { font-family: var(--display); font-size: 56px; font-weight: 700; letter-spacing: -0.03em; line-height: 1.1; }
    \\    .hero h1 span { color: var(--orange); }
    \\    .hero p { max-width: 640px; margin: 20px auto 0; font-size: 18px; color: var(--muted); line-height: 1.6; }
    \\    .hero-stats { display: flex; gap: 16px; justify-content: center; margin-top: 32px; flex-wrap: wrap; }
    \\    .hero-stat { display: inline-flex; align-items: center; gap: 8px; padding: 12px 24px; background: var(--orange-dim); border: 1px solid var(--orange-border); border-radius: 8px; font-family: var(--mono); font-size: 15px; }
    \\    .hero-stat strong { color: var(--orange-dark); font-size: 28px; }
    \\    .badge { display: inline-block; margin-bottom: 16px; padding: 6px 14px; background: var(--orange-dim); border: 1px solid var(--orange-border); border-radius: 20px; font-family: var(--mono); font-size: 11px; color: var(--orange-dark); font-weight: 600; letter-spacing: 0.05em; text-transform: uppercase; }
    \\    .section { max-width: 1000px; margin: 0 auto; padding: 60px 40px; }
    \\    .section-eyebrow { font-family: var(--mono); font-size: 12px; text-transform: uppercase; letter-spacing: 0.1em; color: var(--orange); margin-bottom: 8px; }
    \\    .section h2 { font-family: var(--display); font-size: 32px; font-weight: 700; letter-spacing: -0.02em; margin-bottom: 12px; }
    \\    .section p.sub { color: var(--muted); font-size: 16px; margin-bottom: 40px; }
    \\    .bar-group { margin-bottom: 48px; }
    \\    .bar-group h3 { font-family: var(--display); font-size: 18px; margin-bottom: 20px; }
    \\    .bar-row { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
    \\    .bar-label { width: 220px; font-size: 14px; color: var(--muted); text-align: right; flex-shrink: 0; }
    \\    .bar-track { flex: 1; height: 32px; background: transparent; border-radius: 4px; overflow: hidden; }
    \\    .bar-fill { height: 100%; border-radius: 4px; min-width: 4px; }
    \\    .bar-fill.turbo { background: linear-gradient(90deg, var(--orange), #ffad33); }
    \\    .bar-fill.boto { background: var(--bg3); }
    \\    .bar-fill.zig { background: linear-gradient(90deg, var(--zig), #ffc107); }
    \\    .bar-num { width: 110px; font-family: var(--mono); font-size: 14px; }
    \\    .bar-speedup { font-family: var(--mono); font-size: 13px; color: var(--orange-dark); font-weight: 600; width: 60px; }
    \\    .code-block { background: #1a1612; border: 1px solid #2d2520; border-radius: 8px; padding: 24px; overflow-x: auto; margin: 24px 0; }
    \\    .code-block pre { font-family: var(--mono); font-size: 13px; line-height: 1.6; color: #e8e4dc; }
    \\    .code-block .kw { color: var(--orange); }
    \\    .code-block .str { color: #16a34a; }
    \\    .code-block .cmt { color: #6b7280; }
    \\    .code-block .fn { color: #ffad33; }
    \\    .features { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px; margin: 40px 0; }
    \\    .feature { padding: 24px; background: var(--bg2); border: 1px solid var(--border); border-radius: 8px; }
    \\    .feature h4 { font-family: var(--display); font-size: 16px; margin-bottom: 8px; }
    \\    .feature p { font-size: 14px; color: var(--muted); line-height: 1.5; }
    \\    table { width: 100%; border-collapse: collapse; margin: 24px 0; }
    \\    th, td { padding: 12px 16px; text-align: left; border-bottom: 1px solid var(--border); font-size: 14px; }
    \\    th { font-family: var(--display); font-weight: 600; color: var(--muted); font-size: 12px; text-transform: uppercase; }
    \\    td:nth-child(2), td:nth-child(3), td:nth-child(4) { font-family: var(--mono); }
    \\    .highlight { color: var(--orange-dark); font-weight: 600; }
    \\    .cta-section { text-align: center; padding: 60px 40px; background: var(--bg2); border-top: 1px solid var(--border); }
    \\    .cta-btn { display: inline-block; padding: 14px 32px; background: var(--orange); color: #fff; border-radius: 6px; font-family: var(--display); font-size: 16px; font-weight: 700; }
    \\    .cta-btn:hover { background: var(--orange-dark); text-decoration: none; }
    \\    @media (max-width: 768px) {
    \\      .hero h1 { font-size: 36px; }
    \\      .hero { padding: 60px 20px 40px; }
    \\      .section { padding: 40px 20px; }
    \\      .bar-label { width: 100px; font-size: 12px; }
    \\      .nav-links { display: none; }
    \\      .hero-stats { flex-direction: column; align-items: center; }
    \\    }
    \\  </style>
    \\</head>
    \\<body>
    \\<nav><div class="nav-inner">
    \\  <a href="/" class="wordmark">Turbo<em>Boto</em></a>
    \\  <div class="nav-links">
    \\    <a href="/benchmarks">Benchmarks</a>
    \\    <a href="/turbopg">TurboPG</a>
    \\    <a href="/docs">Docs</a>
    \\    <a href="https://github.com/justrach/turboAPI">GitHub</a>
    \\    <a href="/quickstart" class="nav-cta">Get started</a>
    \\  </div>
    \\</div></nav>
    \\
    \\<div class="hero">
    \\  <div class="badge">Drop-in replacement</div>
    \\  <h1>boto3, but <span>115x faster</span></h1>
    \\  <p>One import line. Zig HTTP transport replaces urllib3. Pair with TurboAPI for the full-stack speedup.</p>
    \\  <div class="hero-stats">
    \\    <div class="hero-stat"><strong>115x</strong> S3 GetObject</div>
    \\    <div class="hero-stat"><strong>162x</strong> S3 ListObjects</div>
    \\    <div class="hero-stat"><strong>170K</strong> req/sec</div>
    \\  </div>
    \\  <p style="color: var(--muted); font-size: 13px; margin-top: 16px; font-family: var(--mono);">TurboAPI + TurboBoto vs FastAPI + boto3</p>
    \\</div>
    \\
    \\<div class="section">
    \\  <div class="section-eyebrow">Developer Experience</div>
    \\  <h2>One line to switch</h2>
    \\  <p class="sub">No config. No setup. Just change the import.</p>
    \\  <div class="code-block"><pre><span class="cmt"># Before</span>
    \\<span class="kw">import</span> boto3
    \\
    \\<span class="cmt"># After — that's it</span>
    \\<span class="kw">import</span> faster_boto3 <span class="kw">as</span> boto3
    \\
    \\<span class="cmt"># Everything works exactly the same</span>
    \\s3 = boto3.<span class="fn">client</span>(<span class="str">'s3'</span>)
    \\s3.<span class="fn">put_object</span>(Bucket=<span class="str">'my-bucket'</span>, Key=<span class="str">'file.txt'</span>, Body=data)
    \\ddb = boto3.<span class="fn">client</span>(<span class="str">'dynamodb'</span>)  <span class="cmt"># works too</span></pre></div>
    \\</div>
    \\
    \\<div class="section" style="border-top: 1px solid var(--border); background: var(--bg2);">
    \\  <div class="section-eyebrow">Full Stack Benchmark</div>
    \\  <h2>TurboAPI + TurboBoto vs FastAPI + boto3</h2>
    \\  <p class="sub">wrk load test: 4 threads, 50 connections, 8 seconds. Both hitting LocalStack S3.</p>
    \\  <div class="bar-group">
    \\    <h3>S3 GetObject (1KB) &mdash; requests/sec</h3>
    \\    <div class="bar-row">
    \\      <div class="bar-label">TurboAPI + TurboBoto</div>
    \\      <div class="bar-track"><div class="bar-fill turbo" style="width:95%"></div></div>
    \\      <div class="bar-num">169,986/s</div>
    \\      <div class="bar-speedup">115x</div>
    \\    </div>
    \\    <div class="bar-row">
    \\      <div class="bar-label">FastAPI + boto3</div>
    \\      <div class="bar-track"><div class="bar-fill boto" style="width:0.9%"></div></div>
    \\      <div class="bar-num">1,470/s</div>
    \\      <div class="bar-speedup"></div>
    \\    </div>
    \\  </div>
    \\  <div class="bar-group">
    \\    <h3>S3 HeadObject &mdash; requests/sec</h3>
    \\    <div class="bar-row">
    \\      <div class="bar-label">TurboAPI + TurboBoto</div>
    \\      <div class="bar-track"><div class="bar-fill turbo" style="width:95%"></div></div>
    \\      <div class="bar-num">167,268/s</div>
    \\      <div class="bar-speedup">102x</div>
    \\    </div>
    \\    <div class="bar-row">
    \\      <div class="bar-label">FastAPI + boto3</div>
    \\      <div class="bar-track"><div class="bar-fill boto" style="width:1%"></div></div>
    \\      <div class="bar-num">1,641/s</div>
    \\      <div class="bar-speedup"></div>
    \\    </div>
    \\  </div>
    \\  <div class="bar-group">
    \\    <h3>S3 ListObjects (20 keys) &mdash; requests/sec</h3>
    \\    <div class="bar-row">
    \\      <div class="bar-label">TurboAPI + TurboBoto</div>
    \\      <div class="bar-track"><div class="bar-fill turbo" style="width:95%"></div></div>
    \\      <div class="bar-num">167,442/s</div>
    \\      <div class="bar-speedup">162x</div>
    \\    </div>
    \\    <div class="bar-row">
    \\      <div class="bar-label">FastAPI + boto3</div>
    \\      <div class="bar-track"><div class="bar-fill boto" style="width:0.6%"></div></div>
    \\      <div class="bar-num">1,031/s</div>
    \\      <div class="bar-speedup"></div>
    \\    </div>
    \\  </div>
    \\</div>
    \\
    \\<div class="section" style="border-top: 1px solid var(--border);">
    \\  <div class="section-eyebrow">Per-Operation</div>
    \\  <h2>Standalone faster-boto3 vs boto3</h2>
    \\  <p class="sub">Same client, same LocalStack. 300 iterations, interleaved A/B, outliers trimmed.</p>
    \\  <table>
    \\    <thead><tr><th>Operation</th><th>boto3</th><th>faster-boto3</th><th>Speedup</th></tr></thead>
    \\    <tbody>
    \\      <tr><td>S3 GetObject (1KB)</td><td>1,396 us</td><td class="highlight">1,176 us</td><td class="highlight">1.19x</td></tr>
    \\      <tr><td>S3 GetObject (10KB)</td><td>1,426 us</td><td class="highlight">1,205 us</td><td class="highlight">1.18x</td></tr>
    \\      <tr><td>S3 GetObject (100KB)</td><td>1,790 us</td><td class="highlight">1,689 us</td><td class="highlight">1.06x</td></tr>
    \\      <tr><td>S3 ListObjectsV2 (20)</td><td>2,352 us</td><td class="highlight">2,096 us</td><td class="highlight">1.12x</td></tr>
    \\      <tr><td>S3 HeadObject</td><td>1,393 us</td><td class="highlight">1,168 us</td><td class="highlight">1.19x</td></tr>
    \\      <tr><td>DynamoDB GetItem</td><td>2,073 us</td><td class="highlight">1,888 us</td><td class="highlight">1.10x</td></tr>
    \\      <tr><td>DynamoDB PutItem</td><td>3,058 us</td><td class="highlight">2,833 us</td><td class="highlight">1.08x</td></tr>
    \\      <tr><td>DynamoDB Scan (30)</td><td>2,866 us</td><td class="highlight">2,653 us</td><td class="highlight">1.08x</td></tr>
    \\    </tbody>
    \\  </table>
    \\  <div class="bar-group">
    \\    <h3>Pure Zig vs Python (HeadObject)</h3>
    \\    <div class="bar-row">
    \\      <div class="bar-label">Pure Zig S3</div>
    \\      <div class="bar-track"><div class="bar-fill zig" style="width:95%"></div></div>
    \\      <div class="bar-num">856 us</div>
    \\      <div class="bar-speedup">1.93x</div>
    \\    </div>
    \\    <div class="bar-row">
    \\      <div class="bar-label">faster-boto3</div>
    \\      <div class="bar-track"><div class="bar-fill turbo" style="width:72%"></div></div>
    \\      <div class="bar-num">1,168 us</div>
    \\      <div class="bar-speedup">1.19x</div>
    \\    </div>
    \\    <div class="bar-row">
    \\      <div class="bar-label">boto3 (urllib3)</div>
    \\      <div class="bar-track"><div class="bar-fill boto" style="width:53%"></div></div>
    \\      <div class="bar-num">1,393 us</div>
    \\      <div class="bar-speedup"></div>
    \\    </div>
    \\  </div>
    \\</div>
    \\
    \\<div class="section" style="border-top: 1px solid var(--border);">
    \\  <div class="section-eyebrow">Under The Hood</div>
    \\  <h2>What Zig replaces</h2>
    \\  <p class="sub">48% of every boto3 call is Python overhead. Zig eliminates the transport layer.</p>
    \\  <div class="features">
    \\    <div class="feature"><h4>Zig HTTP Transport</h4><p>Replaces urllib3 with Zig std.http.Client. Persistent connections, zero-copy streaming, nanobrew pattern.</p></div>
    \\    <div class="feature"><h4>SigV4 Signing (7x)</h4><p>HMAC-SHA256 chain in Zig. 0.6us vs 4.4us per call. Every AWS request benefits.</p></div>
    \\    <div class="feature"><h4>SIMD Timestamps (368x)</h4><p>Replaces dateutil with NEON-vectorized parser. 0.17us vs 62us per timestamp.</p></div>
    \\    <div class="feature"><h4>SHA256 Payload</h4><p>Zig std.crypto for body hashing. Hardware-accelerated on ARM and x86.</p></div>
    \\    <div class="feature"><h4>No GIL</h4><p>Python 3.13t/3.14t free-threaded. Zig modules declare Py_mod_gil = NOT_USED.</p></div>
    \\    <div class="feature"><h4>36/36 Tests Pass</h4><p>Full parity with vanilla boto3. Same API, retries, errors. Drop-in safe.</p></div>
    \\  </div>
    \\</div>
    \\
    \\<div class="cta-section">
    \\  <h2 style="font-family: var(--display); font-size: 32px; margin-bottom: 16px;">One import. Faster AWS.</h2>
    \\  <p style="color: var(--muted); margin-bottom: 24px; font-family: var(--mono);">pip install faster-boto3</p>
    \\  <a href="https://github.com/justrach/turboAPI/tree/faster-boto3" class="cta-btn">View on GitHub</a>
    \\</div>
    \\
    \\</body>
    \\</html>
;
