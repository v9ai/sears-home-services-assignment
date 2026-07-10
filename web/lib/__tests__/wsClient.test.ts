/**
 * CallSocket frame dispatch + serialization (bugfix-loop T13).
 * Every server message flows through handleMessage; malformed drops, unknown
 * types ignored, and format normalization were previously untested.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CallSocket, type CallSocketHandlers } from "../wsClient";

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  static OPEN = 1;
  static CONNECTING = 0;
  url: string;
  readyState = FakeWebSocket.CONNECTING;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    this.readyState = 3;
  }
}

function handlers(): CallSocketHandlers & {
  transcripts: Array<[string, string]>;
  audio: Array<[string, string]>;
  states: unknown[];
} {
  const transcripts: Array<[string, string]> = [];
  const audio: Array<[string, string]> = [];
  const states: unknown[] = [];
  return {
    transcripts,
    audio,
    states,
    onTranscript: (role, text) => transcripts.push([role, text]),
    onAudioChunk: (chunk, format) => audio.push([chunk, format]),
    onState: (caseFile) => states.push(caseFile),
  };
}

describe("CallSocket", () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeWebSocket);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function connected(h = handlers()) {
    const socket = new CallSocket("ws://api.example/", "sess/1", h);
    socket.connect();
    const fake = FakeWebSocket.instances[0];
    return { socket, fake, h };
  }

  it("builds the URL with trailing-slash strip and encoded session id", () => {
    const { fake } = connected();
    expect(fake.url).toBe("ws://api.example/ws/call?session_id=sess%2F1");
  });

  it("dispatches transcript, audio, and state frames to the right handlers", () => {
    const { fake, h } = connected();
    fake.onmessage?.({
      data: JSON.stringify({ type: "transcript", role: "agent", text: "hi" }),
    });
    fake.onmessage?.({
      data: JSON.stringify({ type: "audio", chunk: "aGk=", seq: 0, format: "pcm24k" }),
    });
    fake.onmessage?.({
      data: JSON.stringify({ type: "state", case_file: { safety_flag: false } }),
    });
    expect(h.transcripts).toEqual([["agent", "hi"]]);
    expect(h.audio).toEqual([["aGk=", "pcm24k"]]);
    expect(h.states).toHaveLength(1);
  });

  it("normalizes absent or unknown audio formats to mp3", () => {
    const { fake, h } = connected();
    fake.onmessage?.({ data: JSON.stringify({ type: "audio", chunk: "YQ==", seq: 1 }) });
    fake.onmessage?.({
      data: JSON.stringify({ type: "audio", chunk: "Yg==", seq: 2, format: "wav" }),
    });
    expect(h.audio.map(([, format]) => format)).toEqual(["mp3", "mp3"]);
  });

  it("silently drops malformed JSON and unknown frame types", () => {
    const { fake, h } = connected();
    fake.onmessage?.({ data: "{not json" });
    fake.onmessage?.({ data: JSON.stringify({ type: "mystery", payload: 1 }) });
    expect(h.transcripts).toHaveLength(0);
    expect(h.audio).toHaveLength(0);
    expect(h.states).toHaveLength(0);
  });

  it("sendUserText no-ops unless the socket is OPEN, then sends the frame", () => {
    const { socket, fake } = connected();
    socket.sendUserText("too early");
    expect(fake.sent).toHaveLength(0);
    fake.readyState = FakeWebSocket.OPEN;
    socket.sendUserText("hello");
    expect(JSON.parse(fake.sent[0])).toEqual({ type: "user_text", text: "hello" });
  });
});
