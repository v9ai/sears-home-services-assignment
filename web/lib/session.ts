/**
 * Client-held session id (localStorage), so `/ws/call?session_id=...` can resume the
 * same session on reconnect/reload without adding a new WS frame type to the frozen
 * contract — the server treats an unrecognized id as "create with this id", and a
 * recognized one as "load and resume" (app/agent/session_store.py).
 */

const STORAGE_KEY = "sears.session_id";

function generateId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  // Fallback for environments without crypto.randomUUID (older browsers).
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

export function getOrCreateSessionId(): string {
  if (typeof window === "undefined") return generateId();
  const existing = window.localStorage.getItem(STORAGE_KEY);
  if (existing) return existing;
  const created = generateId();
  window.localStorage.setItem(STORAGE_KEY, created);
  return created;
}

export function resetSessionId(): string {
  const created = generateId();
  if (typeof window !== "undefined") {
    window.localStorage.setItem(STORAGE_KEY, created);
  }
  return created;
}
