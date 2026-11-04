import { Container } from "@cloudflare/containers";

export interface Env {
  MIND_OF_AK_CONTAINER: DurableObjectNamespace<MindOfAKContainer>;
  ASSETS: Fetcher;
}

export class MindOfAKContainer extends Container {
  defaultPort = 8000;
  sleepAfter = "10m";
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname.startsWith("/api/")) {
      const container = env.MIND_OF_AK_CONTAINER.getByName("mind-of-ak-api");
      return container.fetch(request);
    }
    return env.ASSETS.fetch(request);
  },
};
