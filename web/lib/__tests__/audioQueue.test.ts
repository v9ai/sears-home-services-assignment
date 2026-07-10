/**
 * Audio pipeline units (bugfix-loop T13): the byte-vs-base64 concat footgun,
 * strict FIFO blob playback + barge-in stop, and PCM16 decode / gapless
 * scheduling — the app's audio-integrity crown jewels, previously untested.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  AudioPlaybackQueue,
  PcmPlaybackQueue,
  UtteranceAudioBuffer,
  base64ToBytes,
} from "../audioQueue";

function b64(bytes: number[]): string {
  return btoa(String.fromCharCode(...bytes));
}

describe("base64ToBytes", () => {
  it("round-trips known payloads to exact bytes", () => {
    expect(Array.from(base64ToBytes(b64([0, 127, 255, 16])))).toEqual([0, 127, 255, 16]);
    expect(Array.from(base64ToBytes("aGk="))).toEqual([104, 105]); // "hi"
  });
});

describe("UtteranceAudioBuffer", () => {
  it("concatenates decoded bytes across chunks, never the base64 strings", () => {
    const first = [1, 2]; // len 2 -> "AQI=" (padded)
    const second = [3]; // len 1 -> "Aw==" (padded)
    const buffer = new UtteranceAudioBuffer();
    buffer.push(b64(first));
    buffer.push(b64(second));
    const bytes = buffer.flushBytes();
    expect(Array.from(bytes!)).toEqual([1, 2, 3]);
    // The documented footgun: concatenating the base64 STRINGS leaves '='
    // padding mid-stream — not even decodable, let alone valid audio.
    expect(() => base64ToBytes(b64(first) + b64(second))).toThrow();
  });

  it("flush() drains the buffer and empties it", () => {
    const buffer = new UtteranceAudioBuffer();
    expect(buffer.isEmpty).toBe(true);
    buffer.push(b64([9, 9]));
    expect(buffer.isEmpty).toBe(false);
    const blob = buffer.flush("audio/mpeg");
    expect(blob).not.toBeNull();
    expect(blob!.type).toBe("audio/mpeg");
    expect(buffer.isEmpty).toBe(true);
    expect(buffer.flush()).toBeNull();
    expect(buffer.flushBytes()).toBeNull();
  });
});

class FakeAudio {
  static instances: FakeAudio[] = [];
  url: string;
  paused = false;
  private listeners = new Map<string, () => void>();

  constructor(url: string) {
    this.url = url;
    FakeAudio.instances.push(this);
  }

  addEventListener(name: string, fn: () => void): void {
    this.listeners.set(name, fn);
  }

  play(): Promise<void> {
    return Promise.resolve();
  }

  pause(): void {
    this.paused = true;
  }

  end(): void {
    this.listeners.get("ended")?.();
  }
}

describe("AudioPlaybackQueue", () => {
  beforeEach(() => {
    FakeAudio.instances = [];
    let counter = 0;
    vi.stubGlobal("Audio", FakeAudio);
    vi.stubGlobal("URL", {
      createObjectURL: vi.fn(() => `blob:${counter++}`),
      revokeObjectURL: vi.fn(),
    });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  async function tick(): Promise<void> {
    await Promise.resolve();
    await Promise.resolve();
  }

  it("plays blobs strictly in enqueue order, one at a time", async () => {
    const queue = new AudioPlaybackQueue();
    queue.enqueue(new Blob(["a"]));
    queue.enqueue(new Blob(["b"]));
    queue.enqueue(new Blob(["c"]));
    await tick();
    // Only the first clip has started; the rest wait for 'ended'.
    expect(FakeAudio.instances).toHaveLength(1);
    FakeAudio.instances[0].end();
    await tick();
    expect(FakeAudio.instances).toHaveLength(2);
    FakeAudio.instances[1].end();
    await tick();
    expect(FakeAudio.instances).toHaveLength(3);
    expect(FakeAudio.instances.map((a) => a.url)).toEqual(["blob:0", "blob:1", "blob:2"]);
  });

  it("stopAndClear pauses the current clip and drops the queue (barge-in)", async () => {
    const queue = new AudioPlaybackQueue();
    queue.enqueue(new Blob(["a"]));
    queue.enqueue(new Blob(["b"]));
    await tick();
    expect(FakeAudio.instances).toHaveLength(1);
    queue.stopAndClear();
    expect(FakeAudio.instances[0].paused).toBe(true);
    // Finishing the (paused) clip must not resurrect the dropped queue.
    FakeAudio.instances[0].end();
    await tick();
    expect(FakeAudio.instances).toHaveLength(1);
  });
});

class FakeAudioContext {
  static instances: FakeAudioContext[] = [];
  currentTime = 0;
  state = "running";
  destination = {};
  sources: FakeSource[] = [];

  constructor(_opts?: unknown) {
    FakeAudioContext.instances.push(this);
  }

  resume(): Promise<void> {
    this.state = "running";
    return Promise.resolve();
  }

  createBuffer(_channels: number, samples: number, sampleRate: number) {
    return {
      duration: samples / sampleRate,
      channelData: new Float32Array(samples),
      getChannelData(): Float32Array {
        return this.channelData;
      },
    };
  }

  createBufferSource(): FakeSource {
    const source = new FakeSource();
    this.sources.push(source);
    return source;
  }
}

class FakeSource {
  buffer: { duration: number; channelData: Float32Array } | null = null;
  startedAt: number | null = null;
  stopped = false;

  connect(): void {}

  start(at: number): void {
    this.startedAt = at;
  }

  stop(): void {
    this.stopped = true;
  }

  addEventListener(): void {}
}

function pcmBytes(samples: number[]): Uint8Array {
  const bytes = new Uint8Array(samples.length * 2);
  const view = new DataView(bytes.buffer);
  samples.forEach((s, i) => view.setInt16(i * 2, s, true));
  return bytes;
}

describe("PcmPlaybackQueue", () => {
  beforeEach(() => {
    FakeAudioContext.instances = [];
    vi.stubGlobal("AudioContext", FakeAudioContext);
    Object.defineProperty(window, "AudioContext", {
      value: FakeAudioContext,
      configurable: true,
    });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("decodes PCM16-LE to normalized floats", () => {
    const queue = new PcmPlaybackQueue();
    queue.enqueue(pcmBytes([16384, -32768, 0]));
    const context = FakeAudioContext.instances[0];
    const channel = context.sources[0].buffer!.channelData;
    expect(channel[0]).toBeCloseTo(0.5, 5);
    expect(channel[1]).toBeCloseTo(-1.0, 5);
    expect(channel[2]).toBeCloseTo(0.0, 5);
  });

  it("schedules each buffer gaplessly after the previous end", () => {
    const queue = new PcmPlaybackQueue();
    queue.enqueue(pcmBytes(new Array(2400).fill(0))); // 0.1 s at 24 kHz
    queue.enqueue(pcmBytes(new Array(4800).fill(0))); // 0.2 s
    const [first, second] = FakeAudioContext.instances[0].sources;
    expect(first.startedAt).toBe(0);
    expect(second.startedAt).toBeCloseTo(0.1, 5);
  });

  it("ignores sub-sample payloads", () => {
    const queue = new PcmPlaybackQueue();
    queue.enqueue(new Uint8Array([7]));
    expect(FakeAudioContext.instances).toHaveLength(0);
  });

  it("stopAndClear stops every live source and resets the schedule cursor", () => {
    const queue = new PcmPlaybackQueue();
    queue.enqueue(pcmBytes(new Array(2400).fill(0)));
    queue.enqueue(pcmBytes(new Array(2400).fill(0)));
    const context = FakeAudioContext.instances[0];
    context.currentTime = 0.05;
    queue.stopAndClear();
    expect(context.sources.every((s) => s.stopped)).toBe(true);
    // Next enqueue schedules from the context clock, not the stale cursor.
    queue.enqueue(pcmBytes(new Array(2400).fill(0)));
    expect(context.sources[2].startedAt).toBeCloseTo(0.05, 5);
  });
});
