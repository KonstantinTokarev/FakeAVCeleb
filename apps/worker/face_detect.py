"""
Face detection across frames: compute face coverage % and multi_face flag.
MVP: optional opencv/haar or mediapipe; fallback returns default values if not installed.
"""
import os


def detect_faces_in_frames(frame_paths: list[str]) -> tuple[float, bool]:
    """
    Returns (face_coverage_pct, multi_face).
    face_coverage_pct: 0-100, percentage of frames with at least one detected face.
    multi_face: True if any frame has more than one face.
    """
    try:
        import cv2
        cascade = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
        if not os.path.isfile(cascade):
            return 75.0, False  # fallback
        face_cascade = cv2.CascadeClassifier(cascade)
        with_face = 0
        multi = False
        for fp in frame_paths:
            if not os.path.isfile(fp):
                continue
            img = cv2.imread(fp)
            if img is None:
                continue
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, 1.1, 4)
            if len(faces) > 0:
                with_face += 1
            if len(faces) > 1:
                multi = True
        total = len(frame_paths) or 1
        coverage = round(100.0 * with_face / total)
        return float(coverage), multi
    except Exception:
        return 75.0, False
