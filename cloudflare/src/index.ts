export interface Env {
  ASSETS: Fetcher;
  // Set this in the Cloudflare Worker dashboard to the Render backend origin,
  // for example: https://mind-of-ak-api.onrender.com
  API_ORIGIN?: string;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

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
      return fetch(new Request(upstreamUrl.toString(), request));
    }

    return env.ASSETS.fetch(request);
  },
};
