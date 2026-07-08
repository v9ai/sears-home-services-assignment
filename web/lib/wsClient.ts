/**
 * Thin `/ws/call` client — no agent/LLM logic here (tech-stack.md forbidden patterns),
 * just frame (de)serialization and callback dispatch per the frozen WS contract.
 */

import type { CaseFile, ServerFrame, UserTextFrame } from "./types";

export interface CallSocketHandlers {
  onTranscript: (role: "user" | "agent", text: string) => void;
  onAudioChunk: (base64Chunk: string, format: "pcm24k" | "mp3") => void;
  onState: (caseFile: CaseFile) => void;
  onOpen?: () => void;
  onClose?: () => void;
  onError?: (event: Event) => void;
}

export class CallSocket {
  private socket: WebSocket | null = null;

  constructor(
    private readonly wsBaseUrl: string,
    private readonly sessionId: string,
    private readonly handlers: CallSocketHandlers,
  ) {}

  connect(): void {
    const url = `${this.wsBaseUrl.replace(/\/$/, "")}/ws/call?session_id=${encodeURIComponent(
      this.sessionId,
    )}`;
    const socket = new WebSocket(url);
    this.socket = socket;

    socket.onopen = () => this.handlers.onOpen?.();
    socket.onclose = () => this.handlers.onClose?.();
    socket.onerror = (event) => this.handlers.onError?.(event);
    socket.onmessage = (event) => this.handleMessage(event.data);
  }

  private handleMessage(raw: string): void {
    let frame: ServerFrame;
    try {
      frame = JSON.parse(raw) as ServerFrame;
    } catch {
      return;
    }
    switch (frame.type) {
      case "transcript":
        this.handlers.onTranscript(frame.role, frame.text);
        break;
      case "audio":
        this.handlers.onAudioChunk(frame.chunk, frame.format === "pcm24k" ? "pcm24k" : "mp3");
        break;
      case "state":
        this.handlers.onState(frame.case_file);
        break;
    }
  }

  sendUserText(text: string): void {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) return;
    const frame: UserTextFrame = { type: "user_text", text };
    this.socket.send(JSON.stringify(frame));
  }

  close(): void {
    this.socket?.close();
    this.socket = null;
  }
}
