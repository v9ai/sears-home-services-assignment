"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Headset, SendHorizontal, User } from "lucide-react";
import { AudioPlaybackQueue, PcmPlaybackQueue, UtteranceAudioBuffer } from "@/lib/audioQueue";
import { getOrCreateSessionId } from "@/lib/session";
import { CaseFile, EMPTY_CASE_FILE, TranscriptLine } from "@/lib/types";
import { CallSocket } from "@/lib/wsClient";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { CaseFilePanel } from "@/components/case-file-panel";

const WS_BASE_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000";

export default function ChatPage() {
  const [transcript, setTranscript] = useState<TranscriptLine[]>([]);
  const [caseFile, setCaseFile] = useState<CaseFile>(EMPTY_CASE_FILE);
  const [connected, setConnected] = useState(false);
  const [inputValue, setInputValue] = useState("");

  const socketRef = useRef<CallSocket | null>(null);
  const audioQueueRef = useRef<AudioPlaybackQueue | null>(null);
  const pcmQueueRef = useRef<PcmPlaybackQueue | null>(null);
  const utteranceBufferRef = useRef<UtteranceAudioBuffer | null>(null);
  // Format of the utterance currently accumulating in utteranceBufferRef, so the
  // flush routes to the matching playback path (pcm chunks decode differently
  // from mp3 blobs and can never be mixed within one utterance).
  const utteranceFormatRef = useRef<"pcm24k" | "mp3">("mp3");
  const transcriptEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    audioQueueRef.current = new AudioPlaybackQueue();
    pcmQueueRef.current = new PcmPlaybackQueue();
    utteranceBufferRef.current = new UtteranceAudioBuffer();

    const flushUtterance = () => {
      if (utteranceFormatRef.current === "pcm24k") {
        const bytes = utteranceBufferRef.current?.flushBytes();
        if (bytes) pcmQueueRef.current?.enqueue(bytes);
      } else {
        const blob = utteranceBufferRef.current?.flush();
        if (blob) audioQueueRef.current?.enqueue(blob);
      }
    };

    const sessionId = getOrCreateSessionId();
    const socket = new CallSocket(WS_BASE_URL, sessionId, {
      onOpen: () => setConnected(true),
      onClose: () => setConnected(false),
      onError: () => setConnected(false),
      onTranscript: (role, text) => {
        // A new agent line starts a new utterance; flush whatever audio belonged
        // to the previous one first so lines never get merged together.
        flushUtterance();
        setTranscript((prev) => [...prev, { role, text }]);
      },
      onAudioChunk: (chunk, format) => {
        utteranceFormatRef.current = format;
        utteranceBufferRef.current?.push(chunk);
      },
      onState: (nextCaseFile) => {
        flushUtterance();
        setCaseFile(nextCaseFile);
      },
    });
    socketRef.current = socket;
    socket.connect();

    return () => {
      socket.close();
      audioQueueRef.current?.stopAndClear();
      pcmQueueRef.current?.stopAndClear();
    };
  }, []);

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [transcript]);

  const sendMessage = useCallback(() => {
    const text = inputValue.trim();
    if (!text || !socketRef.current) return;
    // First send doubles as the user gesture that unlocks WebAudio playback
    // under the browser autoplay policy.
    void pcmQueueRef.current?.resume();
    socketRef.current.sendUserText(text);
    setInputValue("");
  }, [inputValue]);

  return (
    <div className="flex flex-1 min-h-0 flex-col bg-background text-foreground">
      <div className="flex shrink-0 items-center justify-end border-b px-5 py-2">
        <Badge variant="outline" className="gap-1.5">
          <span
            className={cn(
              "inline-block size-2 rounded-full bg-muted-foreground",
              connected ? "bg-emerald-500" : "animate-pulse"
            )}
          />
          {connected ? "Connected" : "Connecting…"}
        </Badge>
      </div>

      <div className="grid flex-1 grid-cols-1 gap-4 overflow-y-auto p-4 lg:min-h-0 lg:grid-cols-[minmax(0,2fr)_minmax(260px,1fr)] lg:overflow-hidden">
        <Card className="flex h-[60vh] flex-col overflow-hidden py-0 lg:h-auto lg:min-h-0">
          <ScrollArea className="flex-1">
            <div className="flex flex-col gap-2.5 p-4">
              {transcript.length === 0 && (
                <p className="text-sm italic text-muted-foreground">Say hello to get started…</p>
              )}
              {transcript.map((line, index) => (
                <div
                  key={index}
                  className={cn(
                    "flex max-w-[85%] items-end gap-2",
                    line.role === "user" ? "flex-row-reverse self-end" : "self-start"
                  )}
                >
                  <div
                    className={cn(
                      "flex size-6 shrink-0 items-center justify-center rounded-full",
                      line.role === "user"
                        ? "bg-primary/15 text-primary"
                        : "bg-muted text-muted-foreground"
                    )}
                  >
                    {line.role === "user" ? (
                      <User className="size-3.5" />
                    ) : (
                      <Headset className="size-3.5" />
                    )}
                  </div>
                  <div
                    className={cn(
                      "animate-in fade-in-0 slide-in-from-bottom-1 whitespace-pre-wrap rounded-xl px-3 py-2 text-sm leading-normal duration-200",
                      line.role === "user"
                        ? "rounded-br-sm bg-primary text-primary-foreground"
                        : "rounded-bl-sm bg-muted text-foreground"
                    )}
                  >
                    {line.text}
                  </div>
                </div>
              ))}
              <div ref={transcriptEndRef} />
            </div>
          </ScrollArea>
          <form
            className="flex gap-2 border-t p-3"
            onSubmit={(event) => {
              event.preventDefault();
              sendMessage();
            }}
          >
            <Input
              className="flex-1"
              type="text"
              value={inputValue}
              onChange={(event) => setInputValue(event.target.value)}
              placeholder="Describe what's going on with your appliance…"
              aria-label="Message"
            />
            <Button type="submit" disabled={!inputValue.trim()}>
              <SendHorizontal className="size-4" />
              Send
            </Button>
          </form>
        </Card>

        <CaseFilePanel caseFile={caseFile} />
      </div>
    </div>
  );
}
