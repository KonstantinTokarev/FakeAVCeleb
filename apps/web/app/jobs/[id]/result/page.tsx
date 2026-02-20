"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import styles from "./result.module.css";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface Segment {
  start: number;
  end: number;
  score: number;
}

interface Signals {
  face_coverage?: number;
  audio_present?: boolean;
  multi_face?: boolean;
  duration_seconds?: number;
  frames_analyzed?: number;
}

interface Result {
  id: string;
  job_id: string;
  score_overall: number;
  confidence: string;
  segments: Segment[];
  signals: Signals;
  model_meta: { model_name: string; version: string };
}

export default function ResultPage() {
  const params = useParams();
  const id = params.id as string;
  const [result, setResult] = useState<Result | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API_URL}/api/jobs/${id}/result`);
        if (!res.ok) {
          if (!cancelled) setError(res.status === 404 ? "Result not ready." : "Failed to load result.");
          setLoading(false);
          return;
        }
        const data = await res.json();
        if (!cancelled) setResult(data.result);
      } catch {
        if (!cancelled) setError("Network error");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [id]);

  if (loading) {
    return (
      <div className={styles.wrapper}>
        <p className={styles.muted}>Loading result…</p>
      </div>
    );
  }

  if (error || !result) {
    return (
      <div className={styles.wrapper}>
        <h2 className={styles.title}>Unable to load result</h2>
        <p className={styles.muted}>{error || "Not found."}</p>
        <Link href="/" className={styles.link}>← Back to analyzer</Link>
      </div>
    );
  }

  const scorePct = Math.round(result.score_overall * 100);
  const scoreColor =
    scorePct < 40 ? "var(--score-low)" : scorePct < 70 ? "var(--score-mid)" : "var(--score-high)";

  const maxScore = Math.max(...result.segments.map((s) => s.score), 0.01);

  return (
    <div className={styles.wrapper}>
      <h2 className={styles.title}>Analysis result</h2>
      <p className={styles.muted}>Job ID: {result.job_id}</p>

      <div className={styles.scoreCard}>
        <div className={styles.scoreLabel}>Deepfake likelihood</div>
        <div className={styles.scoreValue} style={{ color: scoreColor }}>
          {scorePct}
        </div>
        <div className={styles.scoreSub}>out of 100</div>
        <div className={styles.confidence}>
          Confidence: <strong>{result.confidence}</strong>
        </div>
        {result.model_meta?.model_name && (
          <div className={styles.modelName}>
            Model: {result.model_meta.model_name}
            {result.model_meta.version ? ` (v${result.model_meta.version})` : ""}
          </div>
        )}
      </div>

      {result.segments.length > 0 && (
        <div className={styles.card}>
          <h3 className={styles.cardTitle}>Suspicion by segment</h3>
          <div className={styles.timeline}>
            {result.segments.map((seg, i) => (
              <div
                key={i}
                className={styles.segment}
                title={`${seg.start}s–${seg.end}s: ${Math.round(seg.score * 100)}%`}
                style={{
                  width: `${(seg.end - seg.start) / (result.signals.duration_seconds || seg.end) * 100}%`,
                  height: `${Math.max(20, (seg.score / maxScore) * 100)}%`,
                  backgroundColor: seg.score < 0.4 ? "var(--score-low)" : seg.score < 0.7 ? "var(--score-mid)" : "var(--score-high)",
                }}
              />
            ))}
          </div>
          <div className={styles.segmentLabels}>
            {result.segments.map((seg, i) => (
              <span key={i} className={styles.segmentLabel}>
                {seg.start}s–{seg.end}s
              </span>
            ))}
          </div>
        </div>
      )}

      <div className={styles.card}>
        <h3 className={styles.cardTitle}>What affected reliability</h3>
        <ul className={styles.signals}>
          <li>Face track coverage: {result.signals.face_coverage ?? "—"}%</li>
          <li>Audio present: {result.signals.audio_present ? "Yes" : "No"}</li>
          <li>Multiple faces: {result.signals.multi_face ? "Yes" : "No"}</li>
          {result.signals.duration_seconds != null && (
            <li>Duration: {result.signals.duration_seconds}s</li>
          )}
        </ul>
      </div>

      <div className={styles.actions}>
        <Link href="/" className={styles.primaryBtn}>Analyze another video</Link>
      </div>
    </div>
  );
}
