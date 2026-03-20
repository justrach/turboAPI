// TurboAPI frontend — Cloudflare Workers fetch handler (static pre-rendered HTML).

const securityHeaders = {
  "strict-transport-security": "max-age=63072000; includeSubDomains; preload",
  "x-frame-options": "DENY",
  "x-content-type-options": "nosniff",
  "referrer-policy": "strict-origin-when-cross-origin",
  "cross-origin-opener-policy": "same-origin",
  "permissions-policy": "camera=(), microphone=(), geolocation=()",
};

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    let path = url.pathname;

    // Clean trailing slash
    if (path !== "/" && path.endsWith("/")) {
      path = path.slice(0, -1);
    }

    // Try asset binding first (serves from dist/)
    const assetResponse = await env.ASSETS.fetch(request);
    if (assetResponse.status !== 404) {
      const response = new Response(assetResponse.body, assetResponse);
      for (const [k, v] of Object.entries(securityHeaders)) {
        response.headers.set(k, v);
      }
      return response;
    }

    // 404
    return new Response("Not Found", { status: 404, headers: securityHeaders });
  },
};
