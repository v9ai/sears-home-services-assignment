"use client";

/**
 * Recording detail / replay view — transcript bubbles, play-all sequential audio
 * (reuses web/lib/audioQueue.ts), per-turn play buttons, final case-file panel
 * (specs/features/2026-07-08-call-recording-replay).
 */

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, Headset, Loader2, Play, User } from "lucide-react";
import { AudioPlaybackQueue } from "@/lib/audioQueue";
import { RecordingDetail } from "@/lib/types";
import { CaseFilePanel } from "@/components/case-file-panel";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function RecordingDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;

  const [detail, setDetail] = useState<RecordingDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [playingAll, setPlayingAll] = useState(false);
  const [playingSeq, setPlayingSeq] = useState<number | null>(null);

  const audioQueueRef = useRef<AudioPlaybackQueue | null>(null);
  if (!audioQueueRef.current) {
    audioQueueRef.current = new AudioPlaybackQueue();
  }

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetch(`${API_URL}/api/recordings/${id}`)
      .then((res) => {
        if (res.status === 404) {
          if (!cancelled) setNotFound(true);
          return null;
        }
        return res.json();
      })
      .then((data: RecordingDetail | null) => {
        if (cancelled || !data) return;
        setDetail(data);
      })
      .catch(() => {
        if (!cancelled) setNotFound(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  useEffect(() => {
    return () => {
      audioQueueRef.current?.stopAndClear();
    };
  }, []);

  async function playAll() {
    const queue = audioQueueRef.current;
    if (!queue || !detail) return;
    queue.stopAndClear();
    setPlayingAll(true);
    try {
      for (const turn of detail.transcript) {
        if (turn.audio_seq == null) continue;
        const res = await fetch(`${API_URL}/api/recordings/${id}/audio/${turn.audio_seq}`);
        if (!res.ok) continue;
        const blob = await res.blob();
        queue.enqueue(blob);
      }
    } finally {
      setPlayingAll(false);
    }
  }

  async function playTurn(seq: number) {
    const queue = audioQueueRef.current;
    if (!queue) return;
    queue.stopAndClear();
    setPlayingSeq(seq);
    try {
      const res = await fetch(`${API_URL}/api/recordings/${id}/audio/${seq}`);
      if (!res.ok) return;
      const blob = await res.blob();
      queue.enqueue(blob);
    } finally {
      setPlayingSeq(null);
    }
  }

  return (
    <div className="flex flex-1 min-h-0 flex-col bg-background text-foreground">
      <div className="flex shrink-0 items-center justify-between border-b px-5 py-2">
        <Link href="/recordings" className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-4" />
          Back to recordings
        </Link>
        {detail && (
          <Button type="button" size="sm" disabled={playingAll} onClick={playAll}>
            {playingAll ? <Loader2 className="size-4 animate-spin" /> : <Play className="size-4" />}
            Play all
          </Button>
        )}
      </div>

      {loading && <p className="p-4 text-sm text-muted-foreground">Loading…</p>}
      {notFound && <p className="p-4 text-sm text-muted-foreground">Recording not found.</p>}

      {detail && (
        <div className="grid flex-1 grid-cols-1 gap-4 overflow-y-auto p-4 lg:min-h-0 lg:grid-cols-[minmax(0,2fr)_minmax(260px,1fr)] lg:overflow-hidden">
          <Card className="flex h-[60vh] flex-col overflow-hidden py-0 lg:h-auto lg:min-h-0">
            <ScrollArea className="flex-1">
              <div className="flex flex-col gap-2.5 p-4">
                {detail.transcript.map((turn, index) => (
                  <div
                    key={index}
                    className={cn(
                      "flex max-w-[85%] items-end gap-2",
                      turn.role === "user" ? "flex-row-reverse self-end" : "self-start"
                    )}
                  >
                    <div
                      className={cn(
                        "flex size-6 shrink-0 items-center justify-center rounded-full",
                        turn.role === "user"
                          ? "bg-primary/15 text-primary"
                          : "bg-muted text-muted-foreground"
                      )}
                    >
                      {turn.role === "user" ? (
                        <User className="size-3.5" />
                      ) : (
                        <Headset className="size-3.5" />
                      )}
                    </div>
                    <div
                      className={cn(
                        "flex items-center gap-2 whitespace-pre-wrap rounded-xl px-3 py-2 text-sm leading-normal",
                        turn.role === "user"
                          ? "rounded-br-sm bg-primary text-primary-foreground"
                          : "rounded-bl-sm bg-muted text-foreground"
                      )}
                    >
                      {turn.has_audio && turn.audio_seq != null && (
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon-xs"
                          disabled={playingSeq === turn.audio_seq}
                          onClick={() => playTurn(turn.audio_seq as number)}
                          aria-label="Play this turn"
                        >
                          {playingSeq === turn.audio_seq ? (
                            <Loader2 className="size-3.5 animate-spin" />
                          ) : (
                            <Play className="size-3.5" />
                          )}
                        </Button>
                      )}
                      <span>{turn.text}</span>
                    </div>
                  </div>
                ))}
              </div>
            </ScrollArea>
          </Card>

          <CaseFilePanel caseFile={detail.case_file} />
        </div>
      )}
    </div>
  );
}
