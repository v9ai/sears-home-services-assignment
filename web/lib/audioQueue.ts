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
}
