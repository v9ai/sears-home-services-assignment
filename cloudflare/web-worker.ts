/**
 * Cloudflare Containers Worker entry for the `web` (Next.js frontend) service.
 *
 * Deployed by `wrangler deploy --config wrangler.web.toml` (see `make deploy`),
 * building the SAME `web/Dockerfile` Docker Compose uses locally — per
 * tech-stack.md "Hosting (Cloudflare Containers)": no separate build path.
 *
 * The frontend is a thin client (tech-stack.md): no agent/model/business logic
 * here, just a passthrough to the containerized Next.js server.
 */
import { Container, getContainer } from "@cloudflare/containers";

export class WebContainer extends Container {
  // Matches `EXPOSE 3000` / the `npm run start` bind in web/Dockerfile.
  defaultPort = 3000;
  sleepAfter = "30m";
}

interface Env {
  WEB_CONTAINER: DurableObjectNamespace<WebContainer>;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const container = getContainer(env.WEB_CONTAINER, "singleton");
    return container.fetch(request);
  },
};
