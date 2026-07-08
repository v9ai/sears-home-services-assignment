"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AudioPlaybackQueue, UtteranceAudioBuffer } from "@/lib/audioQueue";
import { getOrCreateSessionId } from "@/lib/session";
import { CaseFile, EMPTY_CASE_FILE, TranscriptLine } from "@/lib/types";
import { CallSocket } from "@/lib/wsClient";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { ScrollArea } from "@/components/ui/scroll-area";

const WS_BASE_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000";

export default function ChatPage() {
  const [transcript, setTranscript] = useState<TranscriptLine[]>([]);
  const [caseFile, setCaseFile] = useState<CaseFile>(EMPTY_CASE_FILE);
  const [connected, setConnected] = useState(false);
  const [inputValue, setInputValue] = useState("");

  const socketRef = useRef<CallSocket | null>(null);
  const audioQueueRef = useRef<AudioPlaybackQueue | null>(null);
  const utteranceBufferRef = useRef<UtteranceAudioBuffer | null>(null);
  const transcriptEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    audioQueueRef.current = new AudioPlaybackQueue();
    utteranceBufferRef.current = new UtteranceAudioBuffer();

    const flushUtterance = () => {
      const blob = utteranceBufferRef.current?.flush();
      if (blob) audioQueueRef.current?.enqueue(blob);
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
      onAudioChunk: (chunk) => {
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
    };
  }, []);

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [transcript]);

  const sendMessage = useCallback(() => {
    const text = inputValue.trim();
    if (!text || !socketRef.current) return;
    socketRef.current.sendUserText(text);
    setInputValue("");
  }, [inputValue]);

  return (
    <div className="flex h-screen flex-col bg-background text-foreground">
      <header className="flex items-center justify-between border-b px-5 py-3">
        <h1 className="text-lg font-semibold">Sears Home Services — Diagnostic Chat</h1>
        <span className="flex items-center text-sm text-muted-foreground">
          <span
            className={cn(
              "mr-1.5 inline-block size-2 rounded-full bg-muted-foreground",
              connected && "bg-emerald-500"
            )}
          />
          {connected ? "Connected" : "Connecting…"}
        </span>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,2fr)_minmax(260px,1fr)] gap-4 p-4">
        <Card className="flex min-h-0 flex-col overflow-hidden py-0">
          <ScrollArea className="flex-1">
            <div className="flex flex-col gap-2.5 p-4">
              {transcript.length === 0 && (
                <p className="text-sm italic text-muted-foreground">Say hello to get started…</p>
              )}
              {transcript.map((line, index) => (
                <div
                  key={index}
                  className={cn(
                    "max-w-[80%] whitespace-pre-wrap rounded-xl px-3 py-2 text-sm leading-normal",
                    line.role === "user"
                      ? "self-end rounded-br-sm bg-primary text-primary-foreground"
                      : "self-start rounded-bl-sm bg-muted text-foreground"
                  )}
                >
                  {line.text}
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
              Send
            </Button>
          </form>
        </Card>

        <CaseFilePanel caseFile={caseFile} />
      </div>
    </div>
  );
}

function CaseFilePanel({ caseFile }: { caseFile: CaseFile }) {
  return (
    <Card className="overflow-y-auto text-sm">
      <CardHeader>
        <CardTitle>Case File</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {caseFile.safety_flag && (
          <Alert variant="destructive">
            <AlertDescription className="font-semibold text-destructive">
              Safety escalation triggered — DIY steps paused.
            </AlertDescription>
          </Alert>
        )}

        <Field label="Appliance">
          {caseFile.appliance_type ?? (
            <span className="italic text-muted-foreground">not yet identified</span>
          )}
        </Field>

        <Field label="Brand / Model">
          {caseFile.brand ?? "—"} / {caseFile.model ?? "—"}
        </Field>

        <Field label="Symptoms">
          {caseFile.symptoms.length === 0 ? (
            <div className="italic text-muted-foreground">none recorded yet</div>
          ) : (
            <div className="flex flex-col gap-2">
              {caseFile.symptoms.map((symptom, index) => (
                <div key={index} className="border-l-2 border-border pl-2.5">
                  <div>{symptom.description}</div>
                  <div className="italic text-muted-foreground">
                    onset: {symptom.onset}
                    {symptom.error_code ? ` · error: ${symptom.error_code}` : ""}
                    {symptom.sound ? ` · sound: ${symptom.sound}` : ""}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Field>

        <Field label="Steps given">
          {caseFile.steps_given.length === 0 ? (
            <div className="italic text-muted-foreground">none yet</div>
          ) : (
            <ol className="list-inside list-decimal">
              {caseFile.steps_given.map((step, index) => (
                <li key={index}>{step}</li>
              ))}
            </ol>
          )}
        </Field>

        <Field label="Customer">
          {caseFile.customer.name ?? "—"}
          {caseFile.customer.zip ? ` · ${caseFile.customer.zip}` : ""}
          {caseFile.customer.email ? ` · ${caseFile.customer.email}` : ""}
        </Field>
      </CardContent>
    </Card>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-0.5 text-xs uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="text-sm">{children}</div>
    </div>
  );
}
