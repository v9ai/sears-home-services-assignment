/**
 * Sequential TTS audio playback queue — decoded blobs play strictly one after another
 * so overlapping sentences never talk over each other.
 */

export class AudioPlaybackQueue {
  private queue: Blob[] = [];
  private playing = false;
  private currentAudio: HTMLAudioElement | null = null;

  enqueue(blob: Blob): void {
    this.queue.push(blob);
    if (!this.playing) {
      void this.playNext();
    }
  }

  stopAndClear(): void {
    this.queue = [];
    if (this.currentAudio) {
      this.currentAudio.pause();
      this.currentAudio = null;
    }
    this.playing = false;
  }

  private async playNext(): Promise<void> {
    const next = this.queue.shift();
    if (!next) {
      this.playing = false;
      return;
    }
    this.playing = true;
    const url = URL.createObjectURL(next);
    const audio = new Audio(url);
    this.currentAudio = audio;
    await new Promise<void>((resolve) => {
      const cleanup = () => {
        URL.revokeObjectURL(url);
        resolve();
      };
      audio.addEventListener("ended", cleanup, { once: true });
      audio.addEventListener("error", cleanup, { once: true });
      audio.play().catch(cleanup);
    });
    this.currentAudio = null;
    await this.playNext();
  }
}

/**
 * Gapless TTS playback for raw PCM16 (mono, 24 kHz little-endian) utterances.
 *
 * Each completed sentence's bytes decode into a WebAudio `AudioBuffer` and are
 * scheduled with `source.start(startAt)` where `startAt` chains onto the end of
 * the previously scheduled buffer — consecutive sentences play back-to-back with
 * zero inter-sentence decode gaps, unlike a fresh `<audio>` element per sentence
 * (the measured ~50–150 ms stutter this replaces, requirements.md L6i/O12).
 */
const PCM_SAMPLE_RATE = 24000;

export class PcmPlaybackQueue {
  private context: AudioContext | null = null;
  private lastScheduledEnd = 0;
  private sources = new Set<AudioBufferSourceNode>();

  /**
   * Resume (or lazily create) the AudioContext from within a user gesture so the
   * browser autoplay policy lets scheduled audio actually sound.
   */
  async resume(): Promise<void> {
    const context = this.ensureContext();
    if (context.state === "suspended") {
      await context.resume();
    }
  }

  enqueue(pcmBytes: Uint8Array): void {
    if (pcmBytes.length < 2) return;
    const context = this.ensureContext();
    void context.resume();

    const samples = pcmBytes.length >> 1; // 2 bytes per Int16 sample
    const buffer = context.createBuffer(1, samples, PCM_SAMPLE_RATE);
    const channel = buffer.getChannelData(0);
    const view = new DataView(pcmBytes.buffer, pcmBytes.byteOffset, samples * 2);
    for (let i = 0; i < samples; i += 1) {
      channel[i] = view.getInt16(i * 2, true) / 32768;
    }

    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(context.destination);

    const startAt = Math.max(context.currentTime, this.lastScheduledEnd);
    source.start(startAt);
    this.lastScheduledEnd = startAt + buffer.duration;

    this.sources.add(source);
    source.addEventListener("ended", () => this.sources.delete(source), {
      once: true,
    });
  }

  stopAndClear(): void {
    for (const source of this.sources) {
      try {
        source.stop();
      } catch {
        // Already stopped/ended — safe to ignore.
      }
    }
    this.sources.clear();
    this.lastScheduledEnd = this.context?.currentTime ?? 0;
  }

  private ensureContext(): AudioContext {
    if (!this.context) {
      const Ctor =
        window.AudioContext ??
        (window as unknown as { webkitAudioContext: typeof AudioContext })
          .webkitAudioContext;
      this.context = new Ctor({ sampleRate: PCM_SAMPLE_RATE });
      this.lastScheduledEnd = this.context.currentTime;
    }
    return this.context;
  }
}

export function base64ToBytes(base64: string): Uint8Array {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

function concatBytes(chunks: Uint8Array[]): Uint8Array {
  const total = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const combined = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    combined.set(chunk, offset);
    offset += chunk.length;
  }
  return combined;
}

/**
 * Accumulates AudioFrame chunks belonging to one spoken line (one server-side
 * TTS `synthesize()` call streams several chunks that only decode as valid audio
 * once concatenated as *bytes* — never concatenate the base64 strings themselves,
 * since each chunk's own base64 padding breaks that) until the caller flushes it
 * into one playable Blob.
 */
export class UtteranceAudioBuffer {
  private parts: Uint8Array[] = [];

  push(base64Chunk: string): void {
    this.parts.push(base64ToBytes(base64Chunk));
  }

  get isEmpty(): boolean {
    return this.parts.length === 0;
  }

  flush(mimeType = "audio/mpeg"): Blob | null {
    if (this.parts.length === 0) return null;
    const combined = concatBytes(this.parts);
    this.parts = [];
    return new Blob([combined.buffer as ArrayBuffer], { type: mimeType });
  }

  /** Raw concatenated bytes for the WebAudio PCM path (no Blob/decode wrapper). */
  flushBytes(): Uint8Array | null {
    if (this.parts.length === 0) return null;
    const combined = concatBytes(this.parts);
    this.parts = [];
    return combined;
  }
}
