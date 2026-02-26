"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import styles from "./result.module.css";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Segment {
  start: number;
  end: number;
  score: number;
  av_score?: number | null;
  artifact_score?: number | null;
}

interface Signals {
  face_coverage?: number;
  has_face?: boolean;
  audio_present?: boolean;
  multi_face?: boolean;
  duration_seconds?: number;
  frames_analyzed?: number;
  frames_flagged?: number;
  video_type?: string;
}

interface FrameVotes {
  ai_generated: number;
  deepfake: number;
  real: number;
  total: number;
  high_confidence_fake?: number;
}

interface VideoTypeMeta {
  type: string;
  label: string;
  confidence: number;
}

interface SubScores {
  av_consistency?: number | null;
  artifact_detection?: number | null;
  temporal?: number | null;
  audio?: number | null;
  frame_votes?: FrameVotes;
  video_type?: VideoTypeMeta;
  weights_used?: Record<string, number>;
}

interface FlaggedFrame {
  index: number;
  score: number;
  findings: Record<string, string>;
}

interface ModelMeta {
  model_name?: string;
  version?: string;
  av_model?: { model_name?: string; version?: string };
  artifact_model?: string;
  temporal_model?: string;
  audio_model?: string;
  type_classifier?: string;
  fusion?: string;
}

/** findings is now a structured object from inference_explain.py */
interface Explanation {
  verdict_text: string;
  verdict_emoji: string;
  confidence_label: string;
  video_type_label: string;
  what_we_checked: string[];
  what_we_found: string[];
  what_to_do: string;
  technical_summary: string;
  type_signals?: Record<string, unknown>;
}

interface Result {
  id: string;
  job_id: string;
  score_overall: number;
  confidence: string;
  verdict: string;
  sub_scores: SubScores;
  /** findings is now an Explanation object, but may be an array in old results */
  findings: Explanation | string[];
  flagged_frames: FlaggedFrame[];
  segments: Segment[];
  signals: Signals;
  model_meta: ModelMeta;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function scoreColor(v: number) {
  return v < 0.4 ? "var(--score-low)" : v < 0.7 ? "var(--score-mid)" : "var(--score-high)";
}

function verdictColor(verdict: string) {
  if (verdict === "likely_fake") return "var(--score-high)";
  if (verdict === "likely_real") return "var(--score-low)";
  return "var(--score-mid)";
}

function ProgressBar({ value, color }: { value: number; color: string }) {
  return (
    <div className={styles.barTrack}>
      <div
        className={styles.barFill}
        style={{ width: `${Math.round(value * 100)}%`, background: color }}
      />
    </div>
  );
}

function SignalBadge({ label, value, positive }: { label: string; value: string; positive?: boolean }) {
  return (
    <div className={styles.badge}>
      <span className={styles.badgeLabel}>{label}</span>
      <span className={styles.badgeValue} style={{ color: positive ? "var(--score-low)" : "var(--text-muted)" }}>
        {value}
      </span>
    </div>
  );
}

// Detect if findings came from the new pipeline (object) or the old (string[])
function getExplanation(findings: Explanation | string[]): Explanation | null {
  if (!findings) return null;
  if (Array.isArray(findings)) return null;
  if (typeof findings === "object" && "verdict_text" in findings) return findings as Explanation;
  return null;
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function ResultPage() {
  const params = useParams();
  const id = params.id as string;
  const [result, setResult] = useState<Result | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showFrames, setShowFrames] = useState(false);
  const [showTech, setShowTech] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API_URL}/api/jobs/${id}/result`);
        if (!res.ok) {
          if (!cancelled)
            setError(res.status === 404 ? "Result not ready." : "Failed to load result.");
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
        <div className={styles.skeleton} />
        <div className={styles.skeleton} style={{ height: 120 }} />
        <div className={styles.skeleton} />
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

  const scorePct    = Math.round(result.score_overall * 100);
  const vc          = verdictColor(result.verdict);
  const maxSeg      = Math.max(...result.segments.map((s) => s.score), 0.01);
  const signals     = result.signals;
  const sub         = result.sub_scores || {};
  const explanation = getExplanation(result.findings);
  const oldFindings = Array.isArray(result.findings) ? (result.findings as string[]) : null;
  const videoType   = sub.video_type;
  const avModel     = result.model_meta?.av_model?.model_name || result.model_meta?.model_name;

  return (
    <div className={styles.wrapper}>

      {/* ── Header ──────────────────────────────────────────────────── */}
      <div className={styles.header}>
        <Link href="/" className={styles.backLink}>← New analysis</Link>
        <span className={styles.jobId}>Job {result.job_id.slice(0, 8)}…</span>
      </div>

      {/* ── Verdict hero ─────────────────────────────────────────────── */}
      <div className={styles.heroCard} style={{ borderColor: vc }}>
        {/* Video type badge — confidence % only shown for FAKE verdicts */}
        {videoType && (
          <div className={styles.typeBadge}>
            {videoType.label}
            {result.verdict === "likely_fake" && videoType.confidence >= 0.6 && (
              <span className={styles.typeConf}>{Math.round(videoType.confidence * 100)}% confident</span>
            )}
          </div>
        )}

        {/* Emoji + verdict text */}
        <div className={styles.verdictEmoji} style={{ color: vc }}>
          {explanation?.verdict_emoji ?? (result.verdict === "likely_fake" ? "🔴" : result.verdict === "likely_real" ? "🟢" : "🟡")}
        </div>

        <div className={styles.verdictText} style={{ color: vc }}>
          {explanation?.verdict_text ?? (
            result.verdict === "likely_fake" ? "This video is likely fake."
              : result.verdict === "likely_real" ? "This video appears authentic."
              : "Results are uncertain."
          )}
        </div>

        <div className={styles.scoreRow}>
          <span className={styles.scoreNum} style={{ color: vc }}>{scorePct}</span>
          <span className={styles.scoreUnit}>/ 100 fake likelihood</span>
        </div>

        <div className={styles.confidenceRow}>
          {explanation?.confidence_label
            ? <><strong>{explanation.confidence_label}</strong></>
            : <><span>Confidence: </span><strong className={styles.conf}>{result.confidence}</strong></>
          }
        </div>
      </div>

      {/* ── What to do ───────────────────────────────────────────────── */}
      {explanation?.what_to_do && (
        <div className={styles.whatToDoCard} style={{ borderLeftColor: vc }}>
          <div className={styles.whatToDoIcon}>💡</div>
          <div className={styles.whatToDoText}>{explanation.what_to_do}</div>
        </div>
      )}

      {/* ── What we checked + What we found (plain-English cards) ───── */}
      {explanation && (
        <div className={styles.twoCol}>
          {/* What we checked */}
          <div className={styles.card}>
            <h3 className={styles.cardTitle}>What we checked</h3>
            <ul className={styles.bulletList}>
              {explanation.what_we_checked.map((item, i) => (
                <li key={i} className={styles.bulletItem}>
                  <span className={styles.bulletDot} style={{ background: "var(--accent)" }} />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>

          {/* What we found */}
          <div className={styles.card}>
            <h3 className={styles.cardTitle}>What we found</h3>
            <ul className={styles.bulletList}>
              {explanation.what_we_found.map((item, i) => (
                <li key={i} className={styles.bulletItem}>
                  <span
                    className={styles.bulletDot}
                    style={{
                      background: item.toLowerCase().includes("no sign") || item.toLowerCase().includes("natural") || item.toLowerCase().includes("authentic")
                        ? "var(--score-low)"
                        : item.toLowerCase().includes("strong") || item.toLowerCase().includes("most")
                        ? "var(--score-high)"
                        : "var(--score-mid)",
                    }}
                  />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {/* Fallback: old reasoning format */}
      {!explanation && oldFindings && oldFindings.length > 0 && (
        <div className={styles.card}>
          <h3 className={styles.cardTitle}>Detection reasoning</h3>
          <ol className={styles.reasoning}>
            {oldFindings.map((f, i) => (
              <li key={i} className={styles.reasoningStep}>
                <span className={styles.stepNum}>{i + 1}</span>
                <span className={styles.stepText}>{f}</span>
              </li>
            ))}
          </ol>
        </div>
      )}

      {/* ── Technical details (collapsible) ─────────────────────────── */}
      <div className={styles.card}>
        <button
          className={styles.toggleBtn}
          onClick={() => setShowTech((v) => !v)}
          aria-expanded={showTech}
        >
          {showTech ? "▲" : "▶"} Technical details
          <span className={styles.toggleHint}>for researchers & advanced users</span>
        </button>

        {/* Always in DOM so @media print can show it even when collapsed */}
        <div className={`${styles.techDetails} ${showTech ? styles.techDetailsOpen : styles.techDetailsHidden}`}>

            {/* Sub-scores */}
            <h4 className={styles.techSubTitle}>Detection sub-scores</h4>
            <div className={styles.subScores}>

              {sub.frame_votes && (
                <div className={styles.subScore}>
                  <div className={styles.subLabel}>
                    Frame classifier — high-confidence fake frames
                    <span className={styles.subPct}>{sub.frame_votes.total} frames total</span>
                  </div>
                  {/* High-confidence fake bar — this is what matters */}
                  {(() => {
                    const hcFake = sub.frame_votes.high_confidence_fake ?? 0;
                    const hcReal = sub.frame_votes.total - hcFake;
                    const hcPct = Math.round((hcFake / sub.frame_votes.total) * 100);
                    return (
                      <>
                        <div className={styles.voteBar}>
                          {hcFake > 0 && (
                            <div
                              className={styles.voteSegment}
                              style={{ width: `${hcPct}%`, background: "var(--score-high)" }}
                              title={`High-confidence fake: ${hcFake} frames`}
                            />
                          )}
                          {hcReal > 0 && (
                            <div
                              className={styles.voteSegment}
                              style={{ width: `${100 - hcPct}%`, background: "var(--score-low)" }}
                              title={`Not flagged: ${hcReal} frames`}
                            />
                          )}
                        </div>
                        <div className={styles.voteLegend}>
                          <span style={{ color: "var(--score-high)" }}>■ High-confidence fake: {hcFake} frames ({hcPct}%)</span>
                          <span style={{ color: "var(--score-low)" }}>■ Not flagged: {hcReal} frames</span>
                        </div>
                        <div className={styles.subHint}>
                          Low-confidence majority votes (for reference only — not used in score):
                          &nbsp;AI {sub.frame_votes.ai_generated} · Deepfake {sub.frame_votes.deepfake} · Real {sub.frame_votes.real}
                        </div>
                      </>
                    );
                  })()}
                  <div className={styles.subHint} style={{ marginTop: "0.5rem" }}>CommunityForensics-DeepfakeDet-ViT — binary frame classifier (Real / Fake). Frames with p_fake ≥ 0.75 are counted as high-confidence.</div>
                </div>
              )}

              {sub.artifact_detection != null && (
                <div className={styles.subScore}>
                  <div className={styles.subLabel}>
                    Frame artifact score
                    <span className={styles.subPct}>{Math.round(sub.artifact_detection * 100)}%</span>
                  </div>
                  <ProgressBar value={sub.artifact_detection} color={scoreColor(sub.artifact_detection)} />
                </div>
              )}

              {sub.av_consistency != null ? (
                <div className={styles.subScore}>
                  <div className={styles.subLabel}>
                    Face-swap / A-V consistency
                    <span className={styles.subPct}>{Math.round(sub.av_consistency * 100)}%</span>
                  </div>
                  <ProgressBar value={sub.av_consistency} color={scoreColor(sub.av_consistency)} />
                  <div className={styles.subHint}>CLIP ViT-L/14 — lip-sync &amp; face-swap</div>
                </div>
              ) : (
                <div className={styles.subScore}>
                  <div className={styles.subLabel}>Face-swap / A-V consistency</div>
                  <div className={styles.subHint} style={{ color: "var(--text-muted)" }}>Skipped — no face or not applicable for this video type</div>
                </div>
              )}

              {sub.temporal != null ? (
                <div className={styles.subScore}>
                  <div className={styles.subLabel}>
                    Temporal motion consistency
                    <span className={styles.subPct}>{Math.round(sub.temporal * 100)}%</span>
                  </div>
                  <ProgressBar value={sub.temporal} color={scoreColor(sub.temporal)} />
                  <div className={styles.subHint}>Optical flow + flicker + texture — catches Sora / Runway / AnimateDiff</div>
                </div>
              ) : (
                <div className={styles.subScore}>
                  <div className={styles.subLabel}>Temporal motion consistency</div>
                  <div className={styles.subHint} style={{ color: "var(--text-muted)" }}>Skipped — insufficient frames</div>
                </div>
              )}

              {sub.audio != null ? (
                <div className={styles.subScore}>
                  <div className={styles.subLabel}>
                    Audio authenticity
                    <span className={styles.subPct}>{Math.round(sub.audio * 100)}%</span>
                  </div>
                  <ProgressBar value={sub.audio} color={scoreColor(sub.audio)} />
                  <div className={styles.subHint}>Wav2Vec2 + signal — voice cloning / TTS (ElevenLabs / XTTS)</div>
                </div>
              ) : (
                <div className={styles.subScore}>
                  <div className={styles.subLabel}>Audio authenticity</div>
                  <div className={styles.subHint} style={{ color: "var(--text-muted)" }}>Skipped — no audio track</div>
                </div>
              )}
            </div>

            {/* Weights used */}
            {sub.weights_used && (
              <>
                <h4 className={styles.techSubTitle} style={{ marginTop: "1.25rem" }}>Fusion weights ({sub.video_type?.type ?? "auto"})</h4>
                <div className={styles.weightGrid}>
                  {Object.entries(sub.weights_used).map(([k, v]) => (
                    <div key={k} className={styles.weightItem}>
                      <span className={styles.weightKey}>{k}</span>
                      <span className={styles.weightVal}>{Math.round(v * 100)}%</span>
                    </div>
                  ))}
                </div>
              </>
            )}

            {/* Technical summary */}
            {explanation?.technical_summary && (
              <>
                <h4 className={styles.techSubTitle} style={{ marginTop: "1.25rem" }}>Summary</h4>
                <pre className={styles.techPre}>{explanation.technical_summary}</pre>
              </>
            )}

            {/* Timeline */}
            {result.segments.length > 0 && (
              <>
                <h4 className={styles.techSubTitle} style={{ marginTop: "1.25rem" }}>Suspicion timeline</h4>
                <div className={styles.timeline}>
                  {result.segments.map((seg, i) => (
                    <div
                      key={i}
                      className={styles.segment}
                      title={`${seg.start}s–${seg.end}s: ${Math.round(seg.score * 100)}%`}
                      style={{
                        flex: seg.end - seg.start,
                        height: `${Math.max(12, (seg.score / maxSeg) * 80)}px`,
                        backgroundColor: scoreColor(seg.score),
                      }}
                    />
                  ))}
                </div>
                <div className={styles.timelineLegend}>
                  <span>0s</span>
                  <span>{signals.duration_seconds ? `${Math.round(signals.duration_seconds)}s` : ""}</span>
                </div>
              </>
            )}

            {/* Signal badges */}
            <h4 className={styles.techSubTitle} style={{ marginTop: "1.25rem" }}>Analysis signals</h4>
            <div className={styles.badgeGrid}>
              <SignalBadge label="Face detected" value={signals.has_face ? "Yes" : "No"} positive={signals.has_face} />
              <SignalBadge label="Face coverage" value={signals.face_coverage != null ? `${signals.face_coverage}%` : "—"} positive={(signals.face_coverage ?? 0) > 50} />
              <SignalBadge label="Audio track" value={signals.audio_present ? "Present" : "None"} positive={signals.audio_present} />
              <SignalBadge label="Multiple faces" value={signals.multi_face ? "Yes" : "No"} />
              <SignalBadge label="Duration" value={signals.duration_seconds != null ? `${Math.round(signals.duration_seconds)}s` : "—"} />
              <SignalBadge label="Frames analyzed" value={String(signals.frames_analyzed ?? "—")} />
              <SignalBadge label="Frames flagged" value={String(signals.frames_flagged ?? 0)} />
            </div>

            {/* Models used */}
            <h4 className={styles.techSubTitle} style={{ marginTop: "1.25rem" }}>Models used</h4>
            <div className={styles.modelList}>
              <div className={styles.modelRow}>
                <span className={styles.modelKey}>Type classifier</span>
                <span className={styles.modelVal}>{result.model_meta?.type_classifier ?? "signal-based"}</span>
              </div>
              <div className={styles.modelRow}>
                <span className={styles.modelKey}>Face-swap (Pass 1)</span>
                <span className={styles.modelVal}>{avModel ?? "baseline_av"}</span>
              </div>
              <div className={styles.modelRow}>
                <span className={styles.modelKey}>Frame classifier (Pass 2)</span>
                <span className={styles.modelVal}>{result.model_meta?.artifact_model ?? "SigLIP2-AI-Deepfake-Real-v2.0"}</span>
              </div>
              <div className={styles.modelRow}>
                <span className={styles.modelKey}>Temporal (Pass 3)</span>
                <span className={styles.modelVal}>{result.model_meta?.temporal_model ?? "optical flow + signal"}</span>
              </div>
              <div className={styles.modelRow}>
                <span className={styles.modelKey}>Audio (Pass 4)</span>
                <span className={styles.modelVal}>{result.model_meta?.audio_model ?? "Wav2Vec2 + signal"}</span>
              </div>
              <div className={styles.modelRow}>
                <span className={styles.modelKey}>Fusion</span>
                <span className={styles.modelVal}>{result.model_meta?.fusion ?? "type-aware weighted"}</span>
              </div>
            </div>

          </div>
      </div>

      {/* ── Flagged frames (collapsible) ─────────────────────────────── */}
      {result.flagged_frames.length > 0 && (
        <div className={styles.card}>
          <button
            className={styles.toggleBtn}
            onClick={() => setShowFrames((v) => !v)}
            aria-expanded={showFrames}
          >
            {showFrames ? "▲" : "▶"} Flagged frames ({result.flagged_frames.length})
          </button>
          <div className={`${styles.framesGrid} ${showFrames ? styles.framesGridOpen : styles.framesGridHidden}`}>
            {result.flagged_frames.map((fr) => (
              <div key={fr.index} className={styles.frameItem}>
                <div className={styles.frameIndex}>Frame #{fr.index}</div>
                <div className={styles.frameScore} style={{ color: scoreColor(fr.score) }}>
                  {Math.round(fr.score * 100)}%
                </div>
                {Object.entries(fr.findings || {}).map(([k, v]) => (
                  <div key={k} className={styles.frameFinding}>{k}: {v}</div>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Actions ───────────────────────────────────────────────────── */}
      <div className={styles.actions}>
        <Link href="/" className={styles.primaryBtn}>Analyze another video</Link>
        <button
          type="button"
          className={styles.exportBtn}
          onClick={() => window.print()}
        >
          Export PDF
        </button>
      </div>
    </div>
  );
}
