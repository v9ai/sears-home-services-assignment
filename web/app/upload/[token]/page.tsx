"use client";

/**
 * Mobile-friendly photo upload page (Tier 3). Thin client only — no agent, model, or
 * business logic here; it just checks token validity and relays the file to the
 * backend's `POST /api/upload/{token}` (tech-stack.md → Forbidden patterns).
 */

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

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
    <main
      style={{
        maxWidth: 480,
        margin: "0 auto",
        padding: "2rem 1.25rem",
        fontFamily: "system-ui, sans-serif",
      }}
    >
      <h1 style={{ fontSize: "1.5rem", marginBottom: "0.5rem" }}>
        Upload a photo of your appliance
      </h1>

      {tokenState === "checking" && <p>Checking your link…</p>}

      {tokenState === "invalid" && (
        <div role="alert" style={{ color: "#b91c1c" }}>
          <p>
            {invalidReason === "expired"
              ? "This upload link has expired. Call us back and we'll send a new one."
              : invalidReason === "already_used"
                ? "A photo has already been uploaded with this link."
                : "This upload link isn't valid."}
          </p>
        </div>
      )}

      {tokenState === "valid" && uploadState !== "done" && (
        <form onSubmit={handleSubmit}>
          <p>Take or choose one photo of the appliance and the issue, if visible.</p>
          <input
            type="file"
            accept="image/jpeg,image/png,image/webp"
            capture="environment"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            style={{ display: "block", margin: "1rem 0" }}
          />
          <button
            type="submit"
            disabled={!file || uploadState === "uploading"}
            style={{
              padding: "0.75rem 1.5rem",
              fontSize: "1rem",
              borderRadius: 6,
              border: "none",
              background: "#1d4ed8",
              color: "white",
              opacity: !file || uploadState === "uploading" ? 0.6 : 1,
            }}
          >
            {uploadState === "uploading" ? "Uploading…" : "Upload photo"}
          </button>
          {uploadState === "error" && (
            <p role="alert" style={{ color: "#b91c1c", marginTop: "1rem" }}>
              {errorMessage}
            </p>
          )}
        </form>
      )}

      {uploadState === "done" && (
        <p>
          Thanks — your photo was received. If you're still on the call, let the agent
          know; otherwise we'll follow up by email with what we found.
        </p>
      )}
    </main>
  );
}
