/**
 * Session-id persistence + UUID shape (bugfix-loop T13). The SSR guard
 * (window undefined) can't be simulated under jsdom; it is covered by the
 * node-environment file next to this one.
 */
import { beforeEach, describe, expect, it } from "vitest";

import { getOrCreateSessionId, resetSessionId } from "../session";

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

describe("session id", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("mints a UUIDv4-shaped id, persists it, and returns it on repeat", () => {
    const first = getOrCreateSessionId();
    expect(first).toMatch(UUID_V4);
    expect(window.localStorage.getItem("sears.session_id")).toBe(first);
    expect(getOrCreateSessionId()).toBe(first);
  });

  it("resetSessionId mints a fresh id and persists it", () => {
    const first = getOrCreateSessionId();
    const second = resetSessionId();
    expect(second).not.toBe(first);
    expect(second).toMatch(UUID_V4);
    expect(window.localStorage.getItem("sears.session_id")).toBe(second);
    expect(getOrCreateSessionId()).toBe(second);
  });
});
