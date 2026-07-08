"use client";

/**
 * Mobile-friendly photo upload page (Tier 3). Thin client only — no agent, model, or
 * business logic here; it just checks token validity and relays the file to the
 * backend's `POST /api/upload/{token}` (tech-stack.md → Forbidden patterns).
 */

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { AlertCircle, CheckCircle2, Loader2, UploadCloud, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { cn } from "@/lib/utils";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type TokenState = "checking" | "valid" | "invalid";
type UploadState = "idle" | "uploading" | "done" | "error";

function formatFileSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function UploadPage() {
  const params = useParams<{ token: string }>();
  const token = params.token;

  const [tokenState, setTokenState] = useState<TokenState>("checking");
  const [invalidReason, setInvalidReason] = useState<string | null>(null);
  const [uploadState, setUploadState] = useState<UploadState>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetch(`${API_URL}/api/upload/${token}`)
      .then((res) => res.json())
      .then((data: { valid: boolean; reason?: string }) => {
        if (cancelled) return;
        setTokenState(data.valid ? "valid" : "invalid");
        setInvalidReason(data.reason ?? null);
      })
      .catch(() => {
        if (!cancelled) {
          setTokenState("invalid");
          setInvalidReason("unknown");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  useEffect(() => {
    if (!file) {
      setPreviewUrl(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setUploadState("uploading");
    setErrorMessage(null);
    try {
      const body = new FormData();
      body.append("file", file);
      const res = await fetch(`${API_URL}/api/upload/${token}`, {
        method: "POST",
        body,
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `Upload failed (${res.status})`);
      }
      setUploadState("done");
    } catch (err) {
      setUploadState("error");
      setErrorMessage(err instanceof Error ? err.message : "Upload failed.");
    }
  }

  return (
    <main className="flex flex-1 items-start justify-center overflow-y-auto bg-background p-4 text-foreground">
      <Card className="mt-8 w-full max-w-md">
        <CardHeader>
          <CardTitle>Upload a photo of your appliance</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {tokenState === "checking" && <p className="text-sm">Checking your link…</p>}

          {tokenState === "invalid" && (
            <Alert variant="destructive">
              <AlertCircle className="size-4" />
              <AlertDescription className="text-destructive">
                {invalidReason === "expired"
                  ? "This upload link has expired. Call us back and we'll send a new one."
                  : invalidReason === "already_used"
                    ? "A photo has already been uploaded with this link."
                    : "This upload link isn't valid."}
              </AlertDescription>
            </Alert>
          )}

          {tokenState === "valid" && uploadState !== "done" && (
            <form className="flex flex-col gap-4" onSubmit={handleSubmit}>
              <p className="text-sm text-muted-foreground">
                Take or choose one photo of the appliance and the issue, if visible.
              </p>

              {previewUrl ? (
                <div className="relative">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={previewUrl}
                    alt="Selected appliance photo"
                    className="aspect-video w-full rounded-lg border object-cover"
                  />
                  <Button
                    type="button"
                    variant="secondary"
                    size="icon-sm"
                    className="absolute right-2 top-2"
                    onClick={() => setFile(null)}
                    aria-label="Remove photo"
                  >
                    <X className="size-4" />
                  </Button>
                  {file && (
                    <p className="mt-1.5 truncate text-xs text-muted-foreground">
                      {file.name} · {formatFileSize(file.size)}
                    </p>
                  )}
                </div>
              ) : (
                <label
                  className={cn(
                    "flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed p-8 text-center transition-colors",
                    isDragging ? "border-primary bg-primary/5" : "border-border"
                  )}
                  onDragOver={(e) => {
                    e.preventDefault();
                    setIsDragging(true);
                  }}
                  onDragLeave={() => setIsDragging(false)}
                  onDrop={(e) => {
                    e.preventDefault();
                    setIsDragging(false);
                    const dropped = e.dataTransfer.files?.[0];
                    if (dropped) setFile(dropped);
                  }}
                >
                  <UploadCloud className="size-8 text-muted-foreground" />
                  <span className="text-sm text-muted-foreground">
                    Tap to choose or drag a photo here
                  </span>
                  <input
                    type="file"
                    accept="image/jpeg,image/png,image/webp"
                    capture="environment"
                    onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                    className="sr-only"
                  />
                </label>
              )}

              <Button type="submit" size="lg" disabled={!file || uploadState === "uploading"}>
                {uploadState === "uploading" && <Loader2 className="size-4 animate-spin" />}
                {uploadState === "uploading" ? "Uploading…" : "Upload photo"}
              </Button>
              {uploadState === "error" && (
                <Alert variant="destructive">
                  <AlertCircle className="size-4" />
                  <AlertDescription className="text-destructive">{errorMessage}</AlertDescription>
                </Alert>
              )}
            </form>
          )}

          {uploadState === "done" && (
            <div className="flex flex-col items-center gap-2 py-4 text-center">
              <CheckCircle2 className="size-8 text-emerald-500" />
              <p className="text-sm">
                Thanks — your photo was received. If you&apos;re still on the call, let the agent
                know; otherwise we&apos;ll follow up by email with what we found.
              </p>
            </div>
          )}
        </CardContent>
      </Card>
    </main>
  );
}
