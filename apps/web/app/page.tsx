"use client";

import { useState } from "react";
import Link from "next/link";
import styles from "./page.module.css";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function LandingPage() {
  const [url, setUrl] = useState("");
  const [uploading, setUploading] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [maxSeconds, setMaxSeconds] = useState(60);
  const [singleFace, setSingleFace] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const startAnalysisByLink = async () => {
    setError(null);
    if (!url.trim()) {
      setError("Please enter a video URL.");
      return;
    }
    try {
      const res = await fetch(`${API_URL}/api/jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          input_type: "link",
          input_url: url.trim(),
          options: { max_seconds: maxSeconds, single_face: singleFace },
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        const msg = data.detail?.message || data.detail?.error_code || JSON.stringify(data.detail);
        setError(msg);
        return;
      }
      window.location.href = `/jobs/${data.job_id}`;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Network error");
    }
  };

  const onFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    setError(null);
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const res = await fetch(`${API_URL}/api/jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          input_type: "upload",
          options: { max_seconds: maxSeconds, single_face: singleFace },
        }),
      });
      let data: { job_id?: string; detail?: { message?: string; error_code?: string } };
      try {
        data = await res.json();
      } catch {
        setError("Invalid response from server");
        setUploading(false);
        return;
      }
      if (!res.ok) {
        setError(data.detail?.message || data.detail?.error_code || "Failed to create job");
        setUploading(false);
        return;
      }
      if (!data.job_id) {
        setError("No job ID returned");
        setUploading(false);
        return;
      }
      const formData = new FormData();
      formData.append("file", file);
      const uploadRes = await fetch(`${API_URL}/api/jobs/${data.job_id}/upload`, {
        method: "POST",
        body: formData,
      });
      let errData: { detail?: { message?: string; error_code?: string } };
      try {
        errData = await uploadRes.json();
      } catch {
        errData = {};
      }
      if (!uploadRes.ok) {
        setError(errData.detail?.error_code || errData.detail?.message || `Upload failed (${uploadRes.status})`);
        setUploading(false);
        return;
      }
      window.location.href = `/jobs/${data.job_id}`;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Network error");
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className={styles.wrapper}>
      <header className={styles.header}>
        <h1 className={styles.title}>Deepfake Detector</h1>
        <p className={styles.subtitle}>
          Analyze a video from a link or upload and get a deepfake likelihood score, confidence, and flagged timestamps.
        </p>
      </header>

      <main className={styles.main}>
        <div className={styles.card}>
          <div className={styles.inputGroup}>
            <label className={styles.label}>Video URL</label>
            <input
              type="url"
              placeholder="https://..."
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              className={styles.input}
              disabled={uploading}
            />
            <button
              type="button"
              onClick={startAnalysisByLink}
              className={styles.primaryBtn}
              disabled={uploading}
            >
              Analyze from link
            </button>
          </div>

          <div className={styles.divider}>
            <span>or</span>
          </div>

          <div className={styles.uploadZone}>
            <label className={styles.uploadLabel}>
              <input
                type="file"
                accept="video/mp4,video/quicktime,video/webm"
                onChange={onFileSelect}
                disabled={uploading}
                className={styles.fileInput}
              />
              {uploading ? "Uploading…" : "Upload video (MP4, MOV, WebM)"}
            </label>
          </div>

          <button
            type="button"
            className={styles.advancedToggle}
            onClick={() => setAdvancedOpen((o) => !o)}
          >
            {advancedOpen ? "▼" : "▶"} Advanced settings
          </button>
          {advancedOpen && (
            <div className={styles.advanced}>
              <label className={styles.option}>
                <span>Analyze first (seconds)</span>
                <input
                  type="number"
                  min={10}
                  max={300}
                  value={maxSeconds}
                  onChange={(e) => setMaxSeconds(Number(e.target.value))}
                  className={styles.smallInput}
                />
              </label>
              <label className={styles.checkbox}>
                <input
                  type="checkbox"
                  checked={singleFace}
                  onChange={(e) => setSingleFace(e.target.checked)}
                />
                Single-face mode (recommended)
              </label>
            </div>
          )}

          {error && <p className={styles.error}>{error}</p>}

          <p className={styles.note}>
            Privacy: We process your video only to produce the analysis. Files are deleted after the retention period (e.g. 24h). We do not train on your content.
          </p>
          <p className={styles.footer}>
            <Link href="/admin">Admin — job logs</Link>
          </p>
        </div>
      </main>
    </div>
  );
}
