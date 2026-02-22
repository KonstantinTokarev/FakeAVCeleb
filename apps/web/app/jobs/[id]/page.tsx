"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import styles from "../job.module.css";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const STEPS = [
  { key: "FETCHING",       label: "Fetching video" },
  { key: "PREPROCESSING",  label: "Preprocessing" },
  { key: "INFERENCING",    label: "Inferencing" },
  { key: "CLASSIFYING",    label: "Classifying video type" },
  { key: "REPORTING",      label: "Reporting" },
];

export default function JobPage() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;
  const [job, setJob] = useState<{
    job_id: string;
    status: string;
    progress: { step: string; done: number; total: number };
    error_code: string | null;
    error_message: string | null;
    result_id: string | null;
  } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    let interval: ReturnType<typeof setInterval>;

    const fetchJob = async () => {
      try {
        const res = await fetch(`${API_URL}/api/jobs/${id}`);
        if (!res.ok) {
          if (res.status === 404) setJob(null);
          setLoading(false);
          return;
        }
        const data = await res.json();
        if (!cancelled) {
          setJob(data);
          if (data.status === "DONE" && data.result_id) {
            clearInterval(interval);
            router.replace(`/jobs/${id}/result`);
            return;
          }
          if (data.status === "FAILED") {
            setLoading(false);
            return;
          }
        }
      } catch {
        if (!cancelled) setLoading(false);
      }
    };

    fetchJob();
    interval = setInterval(fetchJob, 2000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [id, router]);

  if (loading && !job) {
    return (
      <div className={styles.wrapper}>
        <p className={styles.muted}>Loading job…</p>
      </div>
    );
  }

  if (!job) {
    return (
      <div className={styles.wrapper}>
        <h2 className={styles.title}>Job not found</h2>
        <p className={styles.muted}>The analysis job may have expired or the link is invalid.</p>
        <Link href="/" className={styles.link}>← Back to analyzer</Link>
      </div>
    );
  }

  if (job.status === "FAILED") {
    return (
      <div className={styles.wrapper}>
        <h2 className={styles.title}>Analysis failed</h2>
        <p className={styles.errorCode}>{job.error_code || "Unknown error"}</p>
        {job.error_message && <p className={styles.muted}>{job.error_message}</p>}
        <Link href="/" className={styles.link}>← Try again</Link>
      </div>
    );
  }

  // Find active step by matching the current step key name
  const activeIdx = STEPS.findIndex((s) => s.key === job.progress.step);
  // For uploads the first status is "PREPROCESSING" — treat FETCHING as done in that case
  const effectiveActive = activeIdx >= 0 ? activeIdx : 0;

  return (
    <div className={styles.wrapper}>
      <h2 className={styles.title}>Analyzing video</h2>
      <p className={styles.muted}>Job ID: {job.job_id}</p>

      <div className={styles.progressCard}>
        <div className={styles.steps}>
          {STEPS.map((step, i) => {
            const isDone   = i < effectiveActive;
            const isActive = i === effectiveActive;
            return (
              <div
                key={step.key}
                className={`${styles.step} ${isDone ? styles.stepDone : isActive ? styles.stepActive : ""}`}
              >
                <span className={styles.stepNum}>
                  {isDone ? "✓" : i + 1}
                </span>
                <span className={styles.stepLabel}>{step.label}</span>
              </div>
            );
          })}
        </div>
        <p className={styles.progressText}>
          {effectiveActive < STEPS.length - 1
            ? `Step ${effectiveActive + 1} of ${STEPS.length - 1} — ${STEPS[effectiveActive].label}…`
            : "Finishing up…"}
        </p>
      </div>

      <Link href="/" className={styles.link}>← Back to analyzer</Link>
    </div>
  );
}
