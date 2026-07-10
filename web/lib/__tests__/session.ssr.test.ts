// @vitest-environment node
/**
 * SSR half of the session-id contract (T13): with no `window`, an id is still
 * returned (render doesn't crash) but nothing persists.
 */
import { describe, expect, it } from "vitest";

import { getOrCreateSessionId } from "../session";

describe("session id under SSR", () => {
  it("returns an unpersisted id when window is undefined", () => {
    expect(typeof window).toBe("undefined");
    const first = getOrCreateSessionId();
    const second = getOrCreateSessionId();
    expect(first).toBeTruthy();
    expect(second).toBeTruthy();
    // No storage: each SSR call mints fresh (the browser will persist later).
    expect(first).not.toBe(second);
  });
});
