"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AudioPlaybackQueue, UtteranceAudioBuffer } from "@/lib/audioQueue";
import { getOrCreateSessionId } from "@/lib/session";
import { CaseFile, EMPTY_CASE_FILE, TranscriptLine } from "@/lib/types";
import { CallSocket } from "@/lib/wsClient";
import styles from "./chat.module.css";

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
    <div className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.title}>Sears Home Services — Diagnostic Chat</h1>
        <span className={styles.status}>
          <span
            className={`${styles.statusDot} ${connected ? styles.statusDotConnected : ""}`}
          />
          {connected ? "Connected" : "Connecting…"}
        </span>
      </header>

      <div className={styles.body}>
        <section className={styles.chatColumn}>
          <div className={styles.transcript}>
            {transcript.length === 0 && (
              <p className={styles.empty}>Say hello to get started…</p>
            )}
            {transcript.map((line, index) => (
              <div
                key={index}
                className={`${styles.line} ${
                  line.role === "user" ? styles.lineUser : styles.lineAgent
                }`}
              >
                {line.text}
              </div>
            ))}
            <div ref={transcriptEndRef} />
          </div>
          <form
            className={styles.inputRow}
            onSubmit={(event) => {
              event.preventDefault();
              sendMessage();
            }}
          >
            <input
              className={styles.input}
              type="text"
              value={inputValue}
              onChange={(event) => setInputValue(event.target.value)}
              placeholder="Describe what's going on with your appliance…"
              aria-label="Message"
            />
            <button className={styles.sendButton} type="submit" disabled={!inputValue.trim()}>
              Send
            </button>
          </form>
        </section>

        <CaseFilePanel caseFile={caseFile} />
      </div>
    </div>
  );
}

function CaseFilePanel({ caseFile }: { caseFile: CaseFile }) {
  return (
    <aside className={styles.caseFilePanel}>
      <h2 className={styles.caseFileTitle}>Case File</h2>

      {caseFile.safety_flag && (
        <div className={styles.safetyBanner}>
          Safety escalation triggered — DIY steps paused.
        </div>
      )}

      <div className={styles.field}>
        <div className={styles.fieldLabel}>Appliance</div>
        <div className={styles.fieldValue}>
          {caseFile.appliance_type ?? <span className={styles.empty}>not yet identified</span>}
        </div>
      </div>

      <div className={styles.field}>
        <div className={styles.fieldLabel}>Brand / Model</div>
        <div className={styles.fieldValue}>
          {caseFile.brand ?? "—"} / {caseFile.model ?? "—"}
        </div>
      </div>

      <div className={styles.field}>
        <div className={styles.fieldLabel}>Symptoms</div>
        {caseFile.symptoms.length === 0 ? (
          <div className={styles.empty}>none recorded yet</div>
        ) : (
          caseFile.symptoms.map((symptom, index) => (
            <div key={index} className={styles.symptomItem}>
              <div>{symptom.description}</div>
              <div className={styles.empty}>
                onset: {symptom.onset}
                {symptom.error_code ? ` · error: ${symptom.error_code}` : ""}
                {symptom.sound ? ` · sound: ${symptom.sound}` : ""}
              </div>
            </div>
          ))
        )}
      </div>

      <div className={styles.field}>
        <div className={styles.fieldLabel}>Steps given</div>
        {caseFile.steps_given.length === 0 ? (
          <div className={styles.empty}>none yet</div>
        ) : (
          <ol className={styles.stepsList}>
            {caseFile.steps_given.map((step, index) => (
              <li key={index}>{step}</li>
            ))}
          </ol>
        )}
      </div>

      <div className={styles.field}>
        <div className={styles.fieldLabel}>Customer</div>
        <div className={styles.fieldValue}>
          {caseFile.customer.name ?? "—"}
          {caseFile.customer.zip ? ` · ${caseFile.customer.zip}` : ""}
          {caseFile.customer.email ? ` · ${caseFile.customer.email}` : ""}
        </div>
      </div>
    </aside>
  );
}
