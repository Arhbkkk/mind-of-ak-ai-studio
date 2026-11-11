export interface Env {
  ASSETS: { fetch(request: Request): Promise<Response> };
  // HTTPS origin for the Render FastAPI service.
  API_ORIGIN?: string;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    // Access authentication is enforced at Cloudflare's edge for every Worker
    // route. The original CF-Access-Jwt-Assertion header is forwarded to the
    // API, where FastAPI verifies its signature, issuer, and audience.
    if (url.pathname === "/api/worker-status") {
      return Response.json({
        worker: "mind-of-ak-ai-studio",
        api_origin_configured: Boolean(env.API_ORIGIN),
        access_authentication: "cloudflare-edge-and-api-jwt-validation",
      }, { headers: { "Cache-Control": "no-store" } });
    }

    if (url.pathname.startsWith("/api/")) {
      if (!env.API_ORIGIN) {
        return Response.json(
          { detail: "The video-processing backend is not configured yet. Set API_ORIGIN in the Cloudflare Worker settings." },
          { status: 503 }
        );
      }

      let origin: URL;
      try {
        origin = new URL(env.API_ORIGIN);
      } catch {
        return Response.json({ detail: "The configured API_ORIGIN is invalid." }, { status: 500 });
      }
      if (origin.protocol !== "https:") {
        return Response.json({ detail: "API_ORIGIN must use HTTPS." }, { status: 500 });
      }

      const upstreamUrl = new URL(url.pathname + url.search, origin);
      // Preserve the signed Cloudflare Access JWT header for backend
      // verification. Never replace it with a client-controlled identity header.
      return fetch(new Request(upstreamUrl.toString(), request));
    }

    return env.ASSETS.fetch(request);
  },
};
