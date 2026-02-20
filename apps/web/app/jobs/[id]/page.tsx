"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import styles from "../job.module.css";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const STEPS = ["FETCHING", "PREPROCESSING", "INFERENCING", "REPORTING", "DONE"];

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
    const interval = setInterval(fetchJob, 2000);
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

  const stepIndex = STEPS.indexOf(job.progress.step);
  const currentStep = stepIndex >= 0 ? stepIndex + 1 : 0;

  return (
    <div className={styles.wrapper}>
      <h2 className={styles.title}>Analyzing video</h2>
      <p className={styles.muted}>Job ID: {job.job_id}</p>

      <div className={styles.progressCard}>
        <div className={styles.steps}>
          {STEPS.map((step, i) => (
            <div
              key={step}
              className={`${styles.step} ${i < job.progress.done ? styles.stepDone : i === job.progress.done - 1 ? styles.stepActive : ""}`}
            >
              <span className={styles.stepNum}>{i + 1}</span>
              <span className={styles.stepLabel}>{step.replace(/_/g, " ")}</span>
            </div>
          ))}
        </div>
        <p className={styles.progressText}>
          Step {job.progress.done} of {job.progress.total}
        </p>
      </div>

      <Link href="/" className={styles.link}>← Back to analyzer</Link>
    </div>
  );
}
