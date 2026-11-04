export interface Env {
  ASSETS: { fetch(request: Request): Promise<Response> };
  // Set this in the Cloudflare Worker dashboard to the Render backend origin,
  // for example: https://mind-of-ak-api.onrender.com
  API_ORIGIN?: string;
  OWNER_USERNAME?: string;
  OWNER_PASSWORD?: string;
}

function constantTimeEqual(left: string, right: string): boolean {
  let difference = left.length ^ right.length;
  const length = Math.max(left.length, right.length);
  for (let index = 0; index < length; index += 1) {
    difference |= (left.charCodeAt(index) || 0) ^ (right.charCodeAt(index) || 0);
  }
  return difference === 0;
}

function authorized(request: Request, env: Env): boolean {
  const password = env.OWNER_PASSWORD || "";
  if (!password) return false;
  const header = request.headers.get("Authorization") || "";
  if (!header.startsWith("Basic ")) return false;
  try {
    const binary = atob(header.slice(6).trim());
    const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
    const decoded = new TextDecoder().decode(bytes);
    const separator = decoded.indexOf(":");
    if (separator < 0) return false;
    const username = decoded.slice(0, separator);
    const suppliedPassword = decoded.slice(separator + 1);
    return constantTimeEqual(username, env.OWNER_USERNAME || "owner")
      && constantTimeEqual(suppliedPassword, password);
  } catch {
    return false;
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    // Protect both the static application and API proxy. Store OWNER_PASSWORD
    // as a Worker secret; never commit it to this repository.
    if (url.pathname !== "/api/health" && !authorized(request, env)) {
      if (!env.OWNER_PASSWORD) {
        return new Response("Owner access is not configured.", { status: 503 });
      }
      return new Response("Owner sign-in required.", {
        status: 401,
        headers: { "WWW-Authenticate": 'Basic realm="Mind of AK AI Studio", charset="UTF-8"' },
      });
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
      return fetch(new Request(upstreamUrl.toString(), request));
    }

    return env.ASSETS.fetch(request);
  },
};
