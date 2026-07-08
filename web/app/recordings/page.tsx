"use client";

/**
 * Recordings list — dedicated top-level page, no auth
 * (specs/features/2026-07-08-call-recording-replay). Lists every call across both
 * channels, newest first, with an inline quick-play straight from the row.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  ChevronLeft,
  ChevronRight,
  Disc,
  Loader2,
  MessageSquare,
  Phone,
  Play,
} from "lucide-react";
import { AudioPlaybackQueue } from "@/lib/audioQueue";
import { RecordingDetail, RecordingListItem } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const PAGE_SIZE = 20;

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString();
}

function formatDuration(startedAt: string, endedAt: string | null): string {
  if (!endedAt) return "—";
  const ms = new Date(endedAt).getTime() - new Date(startedAt).getTime();
  if (!Number.isFinite(ms) || ms < 0) return "—";
  const totalSeconds = Math.round(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

export default function RecordingsPage() {
  const [items, setItems] = useState<RecordingListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(0);
  const [playingId, setPlayingId] = useState<string | null>(null);

  const audioQueueRef = useRef<AudioPlaybackQueue | null>(null);
  if (!audioQueueRef.current) {
    audioQueueRef.current = new AudioPlaybackQueue();
  }

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetch(`${API_URL}/api/recordings?limit=${PAGE_SIZE}&offset=${offset}`)
      .then((res) => res.json())
      .then((data: RecordingListItem[]) => {
        if (cancelled) return;
        setItems(data);
      })
      .catch(() => {
        if (!cancelled) setItems([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [offset]);

  useEffect(() => {
    return () => {
      audioQueueRef.current?.stopAndClear();
    };
  }, []);

  const quickPlay = useCallback(async (id: string) => {
    const queue = audioQueueRef.current;
    if (!queue) return;
    queue.stopAndClear();
    setPlayingId(id);
    try {
      const res = await fetch(`${API_URL}/api/recordings/${id}`);
      const detail: RecordingDetail = await res.json();
      // Sequential, not Promise.all — playback order must match transcript order.
      for (const turn of detail.transcript) {
        if (turn.audio_seq == null) continue;
        const audioRes = await fetch(`${API_URL}/api/recordings/${id}/audio/${turn.audio_seq}`);
        if (!audioRes.ok) continue;
        const blob = await audioRes.blob();
        queue.enqueue(blob);
      }
    } finally {
      setPlayingId(null);
    }
  }, []);

  return (
    <div className="flex flex-1 min-h-0 flex-col bg-background text-foreground">
      <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-4">
        <h1 className="text-lg font-semibold">Recordings</h1>

        {loading && <p className="text-sm text-muted-foreground">Loading…</p>}

        {!loading && items.length === 0 && (
          <p className="text-sm italic text-muted-foreground">No calls recorded yet.</p>
        )}

        <div className="flex flex-col gap-2">
          {items.map((item) => (
            <Card key={item.id} className="flex flex-row items-center gap-3 p-3">
              <Button
                type="button"
                variant="secondary"
                size="icon-sm"
                disabled={playingId === item.id}
                onClick={() => quickPlay(item.id)}
                aria-label="Quick play"
              >
                {playingId === item.id ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <Play className="size-4" />
                )}
              </Button>

              <Badge variant="outline" className="gap-1.5">
                {item.channel === "phone" ? (
                  <Phone className="size-3.5" />
                ) : (
                  <MessageSquare className="size-3.5" />
                )}
                {item.channel}
              </Badge>

              {item.has_call_sid && (
                <Badge variant="outline" className="gap-1.5" title="Twilio call recording available">
                  <Disc className="size-3.5" />
                  Twilio
                </Badge>
              )}

              <div className="flex flex-1 flex-wrap items-center gap-x-4 gap-y-1 text-sm">
                <span>{formatDateTime(item.started_at)}</span>
                <span className="text-muted-foreground">
                  {item.appliance_type ?? "—"}
                </span>
                <span className="text-muted-foreground">
                  {formatDuration(item.started_at, item.ended_at)}
                </span>
                <span className="text-muted-foreground">{item.turn_count} turns</span>
              </div>

              <Button
                variant="outline"
                size="sm"
                render={<Link href={`/recordings/${item.id}`} />}
              >
                View
              </Button>
            </Card>
          ))}
        </div>

        <div className="flex items-center justify-between pt-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={offset === 0}
            onClick={() => setOffset((prev) => Math.max(0, prev - PAGE_SIZE))}
          >
            <ChevronLeft className="size-4" />
            Previous
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={items.length < PAGE_SIZE}
            onClick={() => setOffset((prev) => prev + PAGE_SIZE)}
          >
            Next
            <ChevronRight className="size-4" />
          </Button>
        </div>
      </div>
    </div>
  );
}
