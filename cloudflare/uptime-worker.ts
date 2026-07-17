/**
 * Uptime monitor for the hosted phone demo — a SEPARATE Worker so it never
 * shares fate with `sears-home-services-app` deploys (the thing it watches).
 *
 * Hourly cron (`5 * * * *`, offset from the app's :00/:10 keep-warm pings):
 *   1. GET  {APP_HOST}/healthz            — container boots ⇒ DB reachable,
 *      migrations+seed ran (the 2026-07-16 outage class: deleted Neon project).
 *   2. POST {APP_HOST}/twilio/voice       — signed exactly like Twilio signs
 *      (HMAC-SHA1 over URL + sorted params) ⇒ exercises signature validation,
 *      PUBLIC_HOST, and TwiML generation; must return <Connect><Stream …>.
 *   3. Twilio REST: the number's voiceUrl still points at the app's webhook
 *      (catches accidental console re-pointing after local-debug sessions).
 *
 * Alerting (state in UPTIME_KV, key "state"):
 *   - any check fails        → 🔴 email EVERY hour while down (review window —
 *     nagging is a feature, not a bug)
 *   - down → up transition   → ✅ "recovered" email immediately
 *   - all green              → one 🟢 digest per day, first healthy run at or
 *     after GREEN_DIGEST_UTC_HOUR (06:00 UTC = 09:00 Chisinau)
 *
 * Email goes through the account's Email Sending worker (`POST {EMAIL_WORKER_URL}/rpc`
 * with a Bearer secret) — same channel agentic-sales uses, verified sender.
 *
 * Manual runs: GET /run?key={RUN_KEY}[&email=1] executes the checks and returns
 * JSON; email is only sent when `email=1` (so a manual probe never spams).
 *
 * Secrets (wrangler secret put … --config wrangler.uptime.toml):
 *   TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, EMAIL_WORKER_URL,
 *   EMAIL_WORKER_SECRET, ALERT_TO, RUN_KEY
 */

interface Env {
  /** Service binding to sears-home-services-app — same-account workers.dev
   * fetches are blocked at the edge (error 1042), so we invoke it directly.
   * URLs passed through it are unchanged, keeping Twilio signatures valid. */
  APP: Fetcher;
  UPTIME_KV: KVNamespace;
  TWILIO_ACCOUNT_SID: string;
  TWILIO_AUTH_TOKEN: string;
  EMAIL_WORKER_URL: string;
  EMAIL_WORKER_SECRET: string;
  ALERT_TO: string;
  RUN_KEY: string;
}

const APP_HOST = "sears-home-services-app.eeeew.workers.dev";
const PHONE_NUMBER = "+13186468479";
const NUMBER_SID = "PN356e3d2a44afd34496997e66fb547da2";
const GREEN_DIGEST_UTC_HOUR = 6; // 09:00 Europe/Chisinau
// Real Twilio's UA — proven to pass the zone's bot filtering (python-urllib is 1010'd).
const UA = "TwilioProxy/1.1";

interface CheckResult {
  name: string;
  ok: boolean;
  detail: string;
}

interface MonitorState {
  status: "up" | "down";
  since: string;
  lastGreenDigest: string; // YYYY-MM-DD
  lastReason: string;
}

async function checkHealthz(env: Env): Promise<CheckResult> {
  try {
    const res = await env.APP.fetch(`https://${APP_HOST}/healthz`, {
      headers: { "User-Agent": UA },
      signal: AbortSignal.timeout(60_000), // first hit may pay the ~33s cold start
    });
    const body = (await res.text()).slice(0, 200);
    return {
      name: "healthz",
      ok: res.status === 200,
      detail: res.status === 200 ? "200" : `HTTP ${res.status}: ${body}`,
    };
  } catch (e) {
    return { name: "healthz", ok: false, detail: `fetch failed: ${e}` };
  }
}

/** Twilio request signature: base64(HMAC-SHA1(authToken, url + concat(sorted k+v))). */
async function twilioSignature(
  authToken: string,
  url: string,
  params: Record<string, string>,
): Promise<string> {
  const payload =
    url +
    Object.keys(params)
      .sort()
      .map((k) => k + params[k])
      .join("");
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(authToken),
    { name: "HMAC", hash: "SHA-1" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(payload));
  return btoa(String.fromCharCode(...new Uint8Array(sig)));
}

async function checkVoiceWebhook(env: Env): Promise<CheckResult> {
  const url = `https://${APP_HOST}/twilio/voice`;
  const params: Record<string, string> = {
    AccountSid: env.TWILIO_ACCOUNT_SID,
    CallSid: "CAdeadbeefdeadbeefdeadbeefdeadbeef", // synthetic monitor call
    From: "+15551234567",
    To: PHONE_NUMBER,
    CallStatus: "ringing",
    Direction: "inbound",
  };
  try {
    const sig = await twilioSignature(env.TWILIO_AUTH_TOKEN, url, params);
    const res = await env.APP.fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Twilio-Signature": sig,
        "User-Agent": UA,
      },
      body: new URLSearchParams(params).toString(),
      signal: AbortSignal.timeout(60_000),
    });
    const body = await res.text();
    const hasStream = body.includes(`<Stream url="wss://${APP_HOST}/ws/twilio">`);
    return {
      name: "voice-webhook",
      ok: res.status === 200 && hasStream,
      detail:
        res.status === 200 && hasStream
          ? "200 + TwiML <Connect><Stream>"
          : `HTTP ${res.status}: ${body.slice(0, 200)}`,
    };
  } catch (e) {
    return { name: "voice-webhook", ok: false, detail: `fetch failed: ${e}` };
  }
}

async function checkNumberConfig(env: Env): Promise<CheckResult> {
  const expected = `https://${APP_HOST}/twilio/voice`;
  try {
    const res = await fetch(
      `https://api.twilio.com/2010-04-01/Accounts/${env.TWILIO_ACCOUNT_SID}/IncomingPhoneNumbers/${NUMBER_SID}.json`,
      {
        headers: {
          Authorization: "Basic " + btoa(`${env.TWILIO_ACCOUNT_SID}:${env.TWILIO_AUTH_TOKEN}`),
        },
        signal: AbortSignal.timeout(30_000),
      },
    );
    if (res.status !== 200) {
      return { name: "number-config", ok: false, detail: `Twilio API HTTP ${res.status}` };
    }
    const data = (await res.json()) as { voice_url?: string; voice_method?: string };
    const ok = data.voice_url === expected && data.voice_method === "POST";
    return {
      name: "number-config",
      ok,
      detail: ok ? "voiceUrl OK" : `voiceUrl=${data.voice_url} method=${data.voice_method}`,
    };
  } catch (e) {
    return { name: "number-config", ok: false, detail: `fetch failed: ${e}` };
  }
}

async function sendEmail(env: Env, subject: string, text: string): Promise<void> {
  const res = await fetch(env.EMAIL_WORKER_URL.replace(/\/$/, "") + "/rpc", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${env.EMAIL_WORKER_SECRET}`,
    },
    body: JSON.stringify({
      op: "send",
      params: { to: env.ALERT_TO, subject, text },
    }),
    signal: AbortSignal.timeout(30_000),
  });
  if (res.status !== 200) {
    // Surface in `wrangler tail` / observability — nothing else we can do.
    console.error(`email send failed: HTTP ${res.status}: ${(await res.text()).slice(0, 300)}`);
  }
}

function report(checks: CheckResult[]): string {
  return checks
    .map((c) => `${c.ok ? "✅" : "❌"} ${c.name}: ${c.detail}`)
    .join("\n");
}

async function runChecks(env: Env): Promise<{ checks: CheckResult[]; allOk: boolean }> {
  const checks = await Promise.all([
    checkHealthz(env),
    checkVoiceWebhook(env),
    checkNumberConfig(env),
  ]);
  return { checks, allOk: checks.every((c) => c.ok) };
}

async function monitor(env: Env, now: Date): Promise<{ checks: CheckResult[]; emailed: string }> {
  let { checks, allOk } = await runChecks(env);
  if (!allOk) {
    // Transient blips happen (a 2026-07-16 test run flapped for one probe and
    // fired a false red) — confirm a failure before alerting.
    await new Promise((r) => setTimeout(r, 15_000));
    ({ checks, allOk } = await runChecks(env));
  }
  const state: MonitorState = (await env.UPTIME_KV.get("state", "json")) ?? {
    status: "up",
    since: now.toISOString(),
    lastGreenDigest: "",
    lastReason: "",
  };
  const today = now.toISOString().slice(0, 10);
  let emailed = "none";

  if (!allOk) {
    const failed = checks.filter((c) => !c.ok).map((c) => c.name).join(", ");
    await sendEmail(
      env,
      `🔴 sears phone demo DOWN (${failed})`,
      `The hosted demo behind ${PHONE_NUMBER} is failing checks as of ${now.toISOString()}.\n` +
        (state.status === "down" ? `Down since: ${state.since}\n` : "") +
        `\n${report(checks)}\n\nApp: https://${APP_HOST}\nRunbook: repo docs/twilio-webhook-setup.md; check Neon project jolly-band-21972353 exists and Worker secrets DATABASE_URL/_DIRECT.`,
    );
    emailed = "red";
    if (state.status === "up") {
      state.status = "down";
      state.since = now.toISOString();
    }
    state.lastReason = report(checks.filter((c) => !c.ok));
  } else {
    if (state.status === "down") {
      await sendEmail(
        env,
        "✅ sears phone demo RECOVERED",
        `All checks green again as of ${now.toISOString()} (was down since ${state.since}; last failing: ${state.lastReason}).\n\n${report(checks)}`,
      );
      emailed = "recovered";
      state.status = "up";
      state.since = now.toISOString();
      // A recovery email IS today's green status — don't double-send.
      state.lastGreenDigest = today;
    } else if (state.lastGreenDigest !== today && now.getUTCHours() >= GREEN_DIGEST_UTC_HOUR) {
      await sendEmail(
        env,
        `🟢 sears phone demo healthy — daily status ${today}`,
        `All checks green at ${now.toISOString()}. Up since ${state.since}.\n\n${report(checks)}\n\nCall it: ${PHONE_NUMBER}`,
      );
      emailed = "green-digest";
      state.lastGreenDigest = today;
    }
  }
  await env.UPTIME_KV.put("state", JSON.stringify(state));
  return { checks, emailed };
}

export default {
  async scheduled(_event: ScheduledEvent, env: Env, ctx: ExecutionContext): Promise<void> {
    ctx.waitUntil(monitor(env, new Date()));
  },

  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname !== "/run" || url.searchParams.get("key") !== env.RUN_KEY) {
      return new Response("not found", { status: 404 });
    }
    if (url.searchParams.get("email") === "1") {
      const result = await monitor(env, new Date());
      return Response.json(result);
    }
    const { checks, allOk } = await runChecks(env);
    return Response.json({ allOk, checks, emailed: "skipped (add &email=1)" });
  },
};
