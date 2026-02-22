"""
Face detection across frames: compute face coverage % and multi_face flag.
MVP: optional opencv/haar or mediapipe; fallback returns default values if not installed.
"""
import os


def detect_faces_in_frames(frame_paths: list[str]) -> tuple[float, bool]:
    """
    Returns (face_coverage_pct, multi_face).
    face_coverage_pct: 0-100, percentage of frames with at least one detected face.
    multi_face: True only when ≥30% of frames have multiple faces (reduces Haar false-positives).
    """
    try:
        import cv2
        cascade = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
        if not os.path.isfile(cascade):
            return 75.0, False  # fallback
        face_cascade = cv2.CascadeClassifier(cascade)
        with_face = 0
        multi_frames = 0
        processed = 0
        for fp in frame_paths:
            if not os.path.isfile(fp):
                continue
            img = cv2.imread(fp)
            if img is None:
                continue
            processed += 1
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            # Stricter params: higher minNeighbors (6) and minSize reduce false double-detections
            faces = face_cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=6, minSize=(40, 40)
            )
            if len(faces) > 0:
                with_face += 1
            if len(faces) > 1:
                multi_frames += 1

        total = processed or 1
        coverage = round(100.0 * with_face / total)
        # Require at least 30% of frames to show multiple faces before flagging multi_face
        multi_face = (multi_frames / total) >= 0.30
        return float(coverage), multi_face
    except Exception:
        return 75.0, False
