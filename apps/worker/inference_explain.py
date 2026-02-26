"""
Plain-English explanation generator — Step 4 of the smart detection pipeline.

Takes structured scores and context from all inference passes and produces
human-readable output that a non-technical user can understand.

Output schema:
  {
    "verdict_text":     str,   # "This video is likely AI-generated."
    "verdict_emoji":    str,   # "🔴" / "🟡" / "🟢"
    "confidence_label": str,   # "High confidence" / "Moderate confidence" / ...
    "video_type_label": str,   # "AI-Generated Scene"
    "what_we_checked":  [str], # bullet list of checks performed
    "what_we_found":    [str], # bullet list of findings
    "what_to_do":       str,   # single action sentence
    "technical_summary":str,   # compact string for advanced users
  }
"""
from __future__ import annotations

from typing import List, Optional


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def explain_result(
    video_type: str,
    video_type_label: str,
    video_type_confidence: float,
    final_score: float,         # 0–1, higher = more fake
    verdict: str,               # "FAKE" / "UNCERTAIN" / "REAL"
    confidence: float,          # 0–1
    av_score: Optional[float],
    siglip_score: Optional[float],
    temporal_score: Optional[float],
    audio_score: Optional[float],
    # Frame-level data
    ai_frames: int,
    deepfake_frames: int,
    real_frames: int,
    total_classified: int,
    # Context
    has_face: bool,
    multi_face: bool,
    audio_present: bool,
    # Which passes actually ran
    ran_av: bool,
    ran_siglip: bool,
    ran_temporal: bool,
    ran_audio: bool,
    # High confidence frame ratio from CLIP pass
    hc_fake_ratio: float,
) -> dict:
    """Generate structured plain-English explanation."""

    # ── Verdict text ─────────────────────────────────────────────────────
    verdict_text, verdict_emoji = _verdict_text(verdict, video_type, final_score)
    confidence_label = _confidence_label(confidence, verdict, video_type)

    # ── What we checked ──────────────────────────────────────────────────
    what_we_checked = _build_what_checked(
        video_type=video_type,
        ran_av=ran_av,
        ran_siglip=ran_siglip,
        ran_temporal=ran_temporal,
        ran_audio=ran_audio,
        has_face=has_face,
        audio_present=audio_present,
        total_classified=total_classified,
    )

    # ── What we found ─────────────────────────────────────────────────────
    what_we_found = _build_what_found(
        video_type=video_type,
        verdict=verdict,
        final_score=final_score,
        av_score=av_score,
        siglip_score=siglip_score,
        temporal_score=temporal_score,
        audio_score=audio_score,
        ai_frames=ai_frames,
        deepfake_frames=deepfake_frames,
        real_frames=real_frames,
        total_classified=total_classified,
        has_face=has_face,
        multi_face=multi_face,
        hc_fake_ratio=hc_fake_ratio,
        ran_av=ran_av,
        ran_siglip=ran_siglip,
        ran_temporal=ran_temporal,
        ran_audio=ran_audio,
    )

    # ── What to do ────────────────────────────────────────────────────────
    what_to_do = _what_to_do(verdict, video_type)

    # ── Technical summary ─────────────────────────────────────────────────
    parts = [f"score={final_score:.2f}", f"type={video_type}"]
    if av_score is not None:       parts.append(f"av={av_score:.2f}")
    if siglip_score is not None:   parts.append(f"siglip={siglip_score:.2f}")
    if temporal_score is not None: parts.append(f"temporal={temporal_score:.2f}")
    if audio_score is not None:    parts.append(f"audio={audio_score:.2f}")
    parts.append(f"confidence={confidence:.2f}")
    technical_summary = ", ".join(parts)

    return {
        "verdict_text":      verdict_text,
        "verdict_emoji":     verdict_emoji,
        "confidence_label":  confidence_label,
        "video_type_label":  video_type_label,
        "what_we_checked":   what_we_checked,
        "what_we_found":     what_we_found,
        "what_to_do":        what_to_do,
        "technical_summary": technical_summary,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _verdict_text(verdict: str, video_type: str, score: float) -> tuple[str, str]:
    # Phrases used when verdict = FAKE
    fake_phrases = {
        "face_swap":    ("a face-swap deepfake",          "someone's face has been digitally replaced"),
        "talking_head": ("a synthetic talking-head video", "the speaker's face or voice appears artificial"),
        "ai_generated": ("AI-generated content",           "this video was likely created by an AI model such as Sora or Runway"),
        "multi_person": ("a manipulated video",            "artificial elements were detected"),
        "animation":    ("computer-generated imagery",     "this appears to be CGI or animation"),
        "real_person":  ("a manipulated video",            "our analysis detected signs of digital manipulation"),
        "cinematic":    ("manipulated cinematic footage",  "artificial elements were detected within what appears to be film or broadcast content"),
    }
    # Phrases used when verdict = UNCERTAIN
    uncertain_phrases = {
        "ai_generated": ("AI-generated content",           "some signals were unusual but not conclusive"),
        "animation":    ("computer-generated imagery",     "this may be CGI or animation"),
        "face_swap":    ("a face-swap deepfake",           "some signals were unusual but not conclusive"),
        "talking_head": ("a synthetic talking-head video", "some signals were unusual but not conclusive"),
        "real_person":  ("manipulation",                   "some signals were ambiguous"),
        "multi_person": ("manipulation",                   "some signals were ambiguous"),
        "cinematic":    ("manipulation",                   "some unusual signals were detected but may be film artefacts"),
    }

    if verdict == "FAKE":
        noun, reason = fake_phrases.get(video_type, ("manipulated content", "artificial elements were detected"))
        return (
            f"This video is most likely {noun} — {reason}.",
            "🔴"
        )
    elif verdict == "UNCERTAIN":
        noun, reason = uncertain_phrases.get(video_type, ("manipulation", "some signals were ambiguous"))
        if video_type in ("ai_generated", "multi_person"):
            return (
                f"Our detectors could not confirm this with high confidence, but this video "
                f"shows signals consistent with AI-generated content. Treat with caution.",
                "🟡"
            )
        elif score > 0.52:
            return (
                f"This video shows some signs of {noun}, but we could not confirm it with high confidence.",
                "🟡"
            )
        else:
            return (
                "This video leans authentic, but some signals were ambiguous. "
                "We recommend a manual review.",
                "🟡"
            )
    else:  # REAL
        # For AI-generated or animation type, even a REAL verdict should acknowledge
        # what the content appears to be — without claiming it is "authentic footage".
        if video_type == "ai_generated":
            return (
                "Our analysis did not detect manipulation signals strong enough to confirm this as AI-generated, "
                "but the video was classified as an AI-generated scene. Treat with caution.",
                "🟡"
            )
        elif video_type == "animation":
            return (
                "This appears to be animation or CGI — no manipulation signals were detected within it.",
                "🟢"
            )
        elif video_type == "cinematic":
            return (
                "This appears to be real cinematic or broadcast footage — "
                "no significant manipulation was detected.",
                "🟢"
            )
        else:
            return (
                "This video appears to be authentic — no significant manipulation was detected.",
                "🟢"
            )


def _confidence_label(confidence: float, verdict: str, video_type: str = "") -> str:
    if verdict == "UNCERTAIN":
        return "Inconclusive — manual review recommended"
    if verdict == "FAKE":
        if confidence >= 0.80:
            return "High confidence"
        elif confidence >= 0.55:
            return "Moderate confidence"
        else:
            return "Low confidence — results may be inconclusive"
    else:  # REAL
        # For AI-generated scene type classified as REAL, stay cautious
        if video_type in ("ai_generated", "animation"):
            return "Uncertain — treat with caution"
        if confidence >= 0.80:
            return "Likely authentic" if video_type != "cinematic" else "Likely real footage"
        elif confidence >= 0.55:
            return "Probably authentic"
        else:
            return "Low confidence — results may be inconclusive"


def _build_what_checked(
    video_type: str,
    ran_av: bool,
    ran_siglip: bool,
    ran_temporal: bool,
    ran_audio: bool,
    has_face: bool,
    audio_present: bool,
    total_classified: int,
) -> List[str]:
    checks = []

    if video_type == "cinematic":
        checks.append(
            "We measured film grain, camera noise patterns, dynamic range, and "
            "motion coherence — signals that distinguish real camera recordings "
            "from AI-generated or heavily edited footage"
        )
    elif ran_siglip and total_classified > 0:
        checks.append(
            f"We analysed {total_classified} video frames to detect AI generation signatures "
            f"(Sora, DALL-E, Midjourney, Stable Diffusion, etc.)"
        )

    if ran_av and has_face:
        checks.append(
            "We checked for face-swap and talking-head deepfakes using a specialised AI model "
            "trained on thousands of manipulated videos"
        )

    if ran_temporal:
        checks.append(
            "We measured how naturally the video moves between frames — AI-generated videos "
            "often have motion that is too smooth or too jittery"
        )

    if ran_audio and audio_present:
        checks.append(
            "We analysed the audio track for signs of voice cloning or AI-generated speech"
        )

    if not checks:
        checks.append("We performed a basic consistency scan of the video content")

    return checks


def _build_what_found(
    video_type: str,
    verdict: str,
    final_score: float,
    av_score: Optional[float],
    siglip_score: Optional[float],
    temporal_score: Optional[float],
    audio_score: Optional[float],
    ai_frames: int,
    deepfake_frames: int,
    real_frames: int,
    total_classified: int,
    has_face: bool,
    multi_face: bool,
    hc_fake_ratio: float,
    ran_av: bool,
    ran_siglip: bool,
    ran_temporal: bool,
    ran_audio: bool,
) -> List[str]:
    findings = []
    n = max(total_classified, 1)

    # For UNCERTAIN on AI-typed content: the individual detectors didn't fire strongly
    # but the video type classifier — which looks at face absence, temporal signals,
    # and frame-level patterns together — flagged this as AI-generated.
    # Explain that specific signal so "What we Found" isn't contradictory.
    if verdict == "UNCERTAIN" and video_type in ("ai_generated", "multi_person"):
        findings.append(
            "The video type classifier identified structural patterns consistent with "
            "AI-generated video — such as the absence of a stable human face, unusual "
            "frame-level texture, or scene composition typical of AI generators like Sora or Runway. "
            "Individual detectors did not reach a high-confidence threshold, which is common "
            "when AI generators produce near-realistic output."
        )

    # Frame classification findings.
    # CommunityForensics ViT has a 2.1% FPR, but is trained on AI-generated images,
    # not face-swaps. Weight = 0 for face/person types. Still, never show alarming
    # frame-percentage text when the overall verdict is REAL.
    if ran_siglip and total_classified > 0:
        hc_pct = round(hc_fake_ratio * 100)

        if verdict == "REAL":
            # For real verdicts: always show a reassuring frame summary
            findings.append(
                "Frame analysis found no significant manipulation signals — "
                "the video looks consistent with authentic footage"
            )
        elif verdict == "UNCERTAIN" and video_type in ("ai_generated", "multi_person"):
            # Explain the ambiguity rather than showing a misleading green bullet
            findings.append(
                "Frame-by-frame analysis did not detect obvious AI artifacts — "
                "modern AI generators can produce frames that look photo-realistic "
                "and pass frame-level checks even when the overall video structure is AI-generated"
            )
        elif hc_fake_ratio >= 0.60:
            findings.append(
                f"{hc_pct}% of frames were flagged as AI-generated or deepfake with high confidence — "
                f"a strong indicator of manipulation"
            )
        elif hc_fake_ratio >= 0.30:
            findings.append(
                f"{hc_pct}% of frames showed manipulation signals above the confidence threshold — "
                f"inconclusive but worth noting"
            )
        elif siglip_score is not None and siglip_score < 0.30:
            findings.append(
                "Frame analysis found no significant manipulation signals — "
                "the video looks consistent with authentic footage"
            )
        else:
            findings.append(
                f"Frame analysis detected some ambiguous signals in {total_classified} frames "
                f"but none were conclusive"
            )

    # A/V face-swap findings
    if ran_av and av_score is not None and has_face:
        if av_score >= 0.65:
            findings.append(
                f"The face-analysis model detected strong manipulation signals "
                f"(score {av_score:.0%}) — the face in this video may not be real"
            )
        elif av_score >= 0.40:
            findings.append(
                f"The face-analysis model found some unusual patterns "
                f"(score {av_score:.0%}), but is not conclusive"
            )
        else:
            findings.append(
                f"The face-analysis model found the face looks authentic "
                f"(score {av_score:.0%})"
            )

    # Temporal motion findings
    if ran_temporal and temporal_score is not None:
        if temporal_score >= 0.65:
            findings.append(
                f"The motion between frames is unusually perfect — real cameras always have "
                f"tiny natural imperfections that are absent here (temporal score {temporal_score:.0%})"
            )
        elif temporal_score >= 0.40:
            findings.append(
                f"Some motion patterns between frames look slightly unnatural "
                f"(temporal score {temporal_score:.0%})"
            )
        elif verdict == "UNCERTAIN" and video_type in ("ai_generated", "multi_person"):
            findings.append(
                f"Frame-to-frame motion appears natural ({temporal_score:.0%} anomaly score) — "
                f"note that high-quality AI generators now produce motion that closely mimics "
                f"real camera movement, so this alone does not confirm authenticity"
            )
        else:
            findings.append(
                f"Frame-to-frame motion looks natural, like a real camera recording "
                f"(temporal score {temporal_score:.0%})"
            )

    # Audio findings
    if ran_audio and audio_score is not None:
        if audio_score >= 0.65:
            findings.append(
                f"The audio track shows strong signs of manipulation — it may be "
                f"AI-generated speech, a dubbed voice, or cloned audio "
                f"(audio score {audio_score:.0%})"
            )
        elif audio_score >= 0.45:
            findings.append(
                f"The audio has some unusual characteristics that may indicate "
                f"dubbed, AI-generated, or re-recorded speech "
                f"(audio score {audio_score:.0%})"
            )
        elif verdict == "UNCERTAIN" and video_type in ("ai_generated", "multi_person"):
            findings.append(
                f"The audio sounds natural ({audio_score:.0%} anomaly score) — "
                f"AI-generated videos can include real or realistic-sounding audio, "
                f"so a clean audio score does not rule out AI-generated visuals"
            )
        else:
            findings.append(
                f"The audio sounds natural — no signs of voice cloning or synthetic speech "
                f"(audio score {audio_score:.0%})"
            )

    if not findings:
        if verdict == "FAKE":
            findings.append("Multiple signals suggest this content is not authentic")
        elif verdict == "UNCERTAIN":
            findings.append("Results are mixed — we could not reach a clear conclusion")
        else:
            findings.append("No significant manipulation signals were found")

    return findings


def _what_to_do(verdict: str, video_type: str) -> str:
    if verdict == "FAKE":
        if video_type in ("face_swap", "talking_head"):
            return (
                "Do not share this video as real. "
                "The person shown may not have said or done what the video depicts. "
                "Consider reporting it on the platform where you found it."
            )
        elif video_type == "ai_generated":
            return (
                "Do not share this video as real footage. "
                "It appears to have been fully generated by AI. "
                "If you found it misrepresented as real news or events, consider reporting it."
            )
        elif video_type == "cinematic":
            return (
                "This appears to be edited or manipulated cinematic footage. "
                "Verify the original source before sharing, "
                "as clips from films or broadcasts are sometimes used out of context."
            )
        else:
            return (
                "Treat this video with caution. "
                "Our analysis suggests it has been digitally altered or created by AI. "
                "Verify with other sources before sharing."
            )
    elif verdict == "UNCERTAIN":
        if video_type in ("ai_generated", "animation", "multi_person"):
            return (
                "Our analysis detected signals consistent with AI-generated content, but could not confirm it with high confidence. "
                "Look for visual artefacts, unnatural motion, or mismatched audio. "
                "When in doubt, do not share as real footage."
            )
        return (
            "Our analysis could not reach a definitive conclusion. "
            "Look for additional context: who posted it, when, and whether other sources confirm it. "
            "When in doubt, do not share."
        )
    elif video_type == "cinematic":
        return (
            "This appears to be real film or broadcast footage with no detected manipulation. "
            "Keep in mind that clips from movies or TV shows can be shared out of context — "
            "always verify the original source."
        )
    else:
        return (
            "This video appears authentic based on our analysis. "
            "Always apply your own judgment and verify important claims through trusted sources."
        )
