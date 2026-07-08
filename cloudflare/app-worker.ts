/**
 * Cloudflare Containers Worker entry for the `app` (FastAPI backend) service.
 *
 * Deployed by `wrangler deploy --config wrangler.app.toml` (see `make deploy`),
 * building the SAME root `Dockerfile` Docker Compose uses locally — per
 * tech-stack.md "Hosting (Cloudflare Containers)": no separate build path.
 *
 * The Worker terminates HTTP + WebSockets and proxies every request straight
 * through to the container instance; this is what gives `/ws/call` (and the
 * Phase 5 Twilio Media Streams bridge, `/ws/twilio`) a public WSS URL without
 * ngrok. Single-tenant demo (mission.md): one always-on instance addressed by
 * a fixed id, no pooling.
 */
import { Container, getContainer } from "@cloudflare/containers";

export class AppContainer extends Container {
  // Matches `EXPOSE 8000` / the uvicorn bind in the root Dockerfile.
  defaultPort = 8000;
  // Keep the container warm across requests during a demo/review window — a
  // cold start re-runs the entrypoint's `alembic upgrade heads` + seed + the
  // LlamaIndex/FastAPI import cost, which is not latency the caller should pay.
  sleepAfter = "30m";
}

interface Env {
  APP_CONTAINER: DurableObjectNamespace<AppContainer>;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const container = getContainer(env.APP_CONTAINER, "singleton");
    // `fetch()` on the container's Durable Object stub proxies the raw request
    // — including the `Upgrade: websocket` handshake — straight to the
    // container's HTTP server. No custom routing needed: FastAPI owns the
    // paths (`/healthz`, `/ws/call`, `/twilio/voice`, `/ws/twilio`, upload
    // routes, ...).
    return container.fetch(request);
  },
};
