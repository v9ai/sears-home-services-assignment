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

// Runtime config the app container needs (tech-stack.md "Hosting"): Worker
// secrets/vars alone are insufficient — they must be passed INTO the container
// process via `Container.envVars`. Sourced from `wrangler secret put <NAME>`
// (see wrangler.app.toml) plus the non-secret `[vars]` in that config.
const APP_CONTAINER_ENV_NAMES = [
  "DATABASE_URL",
  "DATABASE_URL_DIRECT",
  "DEEPSEEK_API_KEY",
  "LLM_PROVIDER",
  "OPENAI_API_KEY",
  "OPENAI_LLM_MODEL",
  "APP_BASE_URL",
  "EMAIL_BACKEND",
  "CF_EMAIL_API_TOKEN",
  "EMAIL_FROM",
  "TWILIO_ACCOUNT_SID",
  "TWILIO_AUTH_TOKEN",
  "TWILIO_PHONE_NUMBER",
  "PUBLIC_HOST",
] as const;

interface Env {
  APP_CONTAINER: DurableObjectNamespace<AppContainer>;
  DATABASE_URL?: string;
  DATABASE_URL_DIRECT?: string;
  DEEPSEEK_API_KEY?: string;
  LLM_PROVIDER?: string;
  OPENAI_API_KEY?: string;
  OPENAI_LLM_MODEL?: string;
  APP_BASE_URL?: string;
  EMAIL_BACKEND?: string;
  CF_EMAIL_API_TOKEN?: string;
  EMAIL_FROM?: string;
  TWILIO_ACCOUNT_SID?: string;
  TWILIO_AUTH_TOKEN?: string;
  TWILIO_PHONE_NUMBER?: string;
  PUBLIC_HOST?: string;
}

export class AppContainer extends Container<Env> {
  // Matches `EXPOSE 8000` / the uvicorn bind in the root Dockerfile.
  defaultPort = 8000;
  // Keep the container warm across requests during a demo/review window — a
  // cold start re-runs the entrypoint's `alembic upgrade heads` + seed + the
  // LlamaIndex/FastAPI import cost, which is not latency the caller should pay.
  sleepAfter = "30m";

  constructor(ctx: DurableObjectState<Env>, env: Env) {
    super(ctx, env);
    const envVars: Record<string, string> = {};
    for (const name of APP_CONTAINER_ENV_NAMES) {
      const value = env[name];
      if (typeof value === "string" && value.length > 0) {
        envVars[name] = value;
      }
    }
    this.envVars = envVars;
  }
}

export default {
  // O11 keep-warm: the cron trigger pings /healthz through the container so the
  // singleton DO instance never crosses sleepAfter and cold-starts on a reviewer.
  async scheduled(_event: ScheduledEvent, env: Env): Promise<void> {
    const container = getContainer(env.APP_CONTAINER, "singleton-v3");
    await container.fetch(new Request("http://container/healthz"));
  },

  async fetch(request: Request, env: Env): Promise<Response> {
    // NOTE: the DO instance id is bumped whenever container envVars change
    // (e.g. a new/rotated secret) — Container.envVars is captured once at DO
    // construction time, so an already-running singleton instance does NOT
    // pick up newly-set `wrangler secret put` values on its own; only a fresh
    // DO instance (new id) re-reads `env` and re-populates envVars. A plain
    // `wrangler deploy` alone is NOT sufficient after a secret change.
    // v3: envVars contract extended (OPENAI_LLM_MODEL, 2026-07-08 model pin) — new
    // DO id forces a fresh instance that re-reads env (see NOTE above).
    const container = getContainer(env.APP_CONTAINER, "singleton-v3");
    // `fetch()` on the container's Durable Object stub proxies the raw request
    // — including the `Upgrade: websocket` handshake — straight to the
    // container's HTTP server. No custom routing needed: FastAPI owns the
    // paths (`/healthz`, `/ws/call`, `/twilio/voice`, `/ws/twilio`, upload
    // routes, ...).
    return container.fetch(request);
  },
};
