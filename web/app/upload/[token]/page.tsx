"use client";

/**
 * Mobile-friendly photo upload page (Tier 3). Thin client only — no agent, model, or
 * business logic here; it just checks token validity and relays the file to the
 * backend's `POST /api/upload/{token}` (tech-stack.md → Forbidden patterns).
 */

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type TokenState = "checking" | "valid" | "invalid";
type UploadState = "idle" | "uploading" | "done" | "error";

export default function UploadPage() {
  const params = useParams<{ token: string }>();
  const token = params.token;

  const [tokenState, setTokenState] = useState<TokenState>("checking");
  const [invalidReason, setInvalidReason] = useState<string | null>(null);
  const [uploadState, setUploadState] = useState<UploadState>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);

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
    <main className="flex min-h-screen items-start justify-center bg-background p-4 text-foreground">
      <Card className="mt-8 w-full max-w-md">
        <CardHeader>
          <CardTitle>Upload a photo of your appliance</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {tokenState === "checking" && <p className="text-sm">Checking your link…</p>}

          {tokenState === "invalid" && (
            <Alert variant="destructive">
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
              <Input
                type="file"
                accept="image/jpeg,image/png,image/webp"
                capture="environment"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
              <Button type="submit" disabled={!file || uploadState === "uploading"}>
                {uploadState === "uploading" ? "Uploading…" : "Upload photo"}
              </Button>
              {uploadState === "error" && (
                <Alert variant="destructive">
                  <AlertDescription className="text-destructive">{errorMessage}</AlertDescription>
                </Alert>
              )}
            </form>
          )}

          {uploadState === "done" && (
            <p className="text-sm">
              Thanks — your photo was received. If you&apos;re still on the call, let the agent
              know; otherwise we&apos;ll follow up by email with what we found.
            </p>
          )}
        </CardContent>
      </Card>
    </main>
  );
}
