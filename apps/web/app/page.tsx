"use client";

import Image from "next/image";
import Link from "next/link";
import { useEffect, useState } from "react";
import styles from "./page.module.css";
import { getOrCreateAnonymousId, setAnonymousId } from "../lib/anonymousId";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function LandingPage() {
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [paymentRequired, setPaymentRequired] = useState(false);
  const [paying, setPaying] = useState(false);
  const [nextCheckFree, setNextCheckFree] = useState<boolean | null>(null);
  const maxSeconds = 60;
  const singleFace = false;

  const startCheckout = async () => {
    setError(null);
    setPaying(true);
    try {
      const anonymousId = getOrCreateAnonymousId();
      const res = await fetch(`${API_URL}/api/payment/create-checkout`, {
        method: "POST",
        headers: { "X-Anonymous-Id": anonymousId },
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = (data as { detail?: { message?: string; code?: string } }).detail;
        setError(detail?.message || detail?.code || `Payment failed (${res.status})`);
        return;
      }
      const url = (data as { checkout_url?: string }).checkout_url;
      if (!url) {
        setError("No checkout URL returned");
        return;
      }
      window.location.href = url;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Network error");
    } finally {
      setPaying(false);
    }
  };

  const onFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    setError(null);
    setPaymentRequired(false);
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const anonymousId = getOrCreateAnonymousId();
      const res = await fetch(`${API_URL}/api/jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Anonymous-Id": anonymousId },
        body: JSON.stringify({
          input_type: "upload",
          options: { max_seconds: maxSeconds, single_face: singleFace },
        }),
      });
      let data: {
        job_id?: string;
        anonymous_id?: string | null;
        detail?: { message?: string; error_code?: string; code?: string };
      };
      try {
        data = await res.json();
      } catch {
        setError("Invalid response from server");
        setUploading(false);
        return;
      }
      if (res.status === 429) {
        setError(data.detail?.message || "Free check limit reached for this network. Try again tomorrow or pay 1 €.");
        setUploading(false);
        return;
      }
      if (res.status === 402) {
        setPaymentRequired(true);
        setError(data.detail?.message || "Payment required (1 €)");
        setUploading(false);
        return;
      }
      if (!res.ok) {
        setError(data.detail?.message || data.detail?.error_code || data.detail?.code || "Failed to create job");
        setUploading(false);
        return;
      }
      if (!data.job_id) {
        setError("No job ID returned");
        setUploading(false);
        return;
      }
      // If server generated a new ID (missing/invalid header), persist it.
      if (data.anonymous_id) setAnonymousId(data.anonymous_id);
      const formData = new FormData();
      formData.append("file", file);
      const uploadRes = await fetch(`${API_URL}/api/jobs/${data.job_id}/upload`, {
        method: "POST",
        headers: { "X-Anonymous-Id": getOrCreateAnonymousId() },
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

  // Fetch /api/me once to show whether next check is free or paid
  useEffect(() => {
    (async () => {
      try {
        const anonymousId = getOrCreateAnonymousId();
        const res = await fetch(`${API_URL}/api/me`, {
          headers: { "X-Anonymous-Id": anonymousId },
        });
        if (!res.ok) return;
        const data = (await res.json()) as { next_check_free?: boolean };
        if (typeof data.next_check_free === "boolean") {
          setNextCheckFree(data.next_check_free);
        }
      } catch {
        // ignore; hint is optional
      }
    })();
  }, []);

  return (
    <div className={styles.wrapper}>
      <header className={styles.header}>
        <Link href="/" className={styles.logoRow} aria-label="Deepfake Detector home">
          <Image src="/logo.png" alt="So Deepfake Detector" width={560} height={224} className={styles.logo} priority />
        </Link>
        <p className={styles.subtitle}>
          Upload a video to get a deepfake likelihood score, confidence, and flagged timestamps.
        </p>
      </header>

      <main className={styles.main}>
        <div className={styles.card}>
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

          {error && <p className={styles.error}>{error}</p>}
          {paymentRequired && (
            <div className={styles.payBox}>
              <button
                type="button"
                className={styles.payBtn}
                onClick={startCheckout}
                disabled={paying || uploading}
              >
                {paying ? "Opening payment…" : "Pay 1 €"}
              </button>
              <p className={styles.payHint}>After payment, come back and upload your video again.</p>
            </div>
          )}

          {nextCheckFree != null && (
            <p className={styles.nextHint}>
              Next check: {nextCheckFree ? "free" : "1 €"}
            </p>
          )}

          <p className={styles.note}>
            Privacy: We process your video only to produce the analysis. Files are deleted after the retention period of 7 days. We do not train on your content.
          </p>
        </div>
      </main>
    </div>
  );
}
