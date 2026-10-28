"""
PPE Helmet Detection - Standalone Webcam Test
Uses OpenCV face detection + custom YOLOv8 hard-hat model for helmets.
Part of: AI-Based Smart PPE Compliance Monitoring System (Industrial IoT)

Detection logic (both detectors run independently):
  - Helmet detected → HELMET DETECTED   (green)  person must be wearing it
  - Face but no helmet → NO HELMET       (red)    person present, no PPE
  - Neither → NO PERSON DETECTED         (yellow) nobody in frame

Usage:
  python helmet_webcam_test.py

Controls:
  q - Quit and release webcam
"""

import sys
import time
from pathlib import Path

# --- Configuration ---
HELMET_MODEL_PATH = Path(__file__).parent / "models" / "last_hardhat_200_epochs.pt"
CONFIDENCE_THRESHOLD = 0.45   # Helmet detection confidence
INFERENCE_SIZE = 320          # Smaller = faster on CPU
SKIP_FRAMES = 2              # Run inference every N frames (1 = every frame)
WEBCAM_INDEX = 0              # 0 = default built-in webcam
WINDOW_NAME = "PPE Helmet Detection - Press Q to Quit"
# Face detector tuning (relaxed for better detection)
FACE_SCALE_FACTOR = 1.1       # Finer steps = catches more faces
FACE_MIN_NEIGHBORS = 3        # Lower = more sensitive (was 5, too strict)
FACE_MIN_SIZE = (40, 40)      # Minimum face size in pixels

def check_dependencies():
    """Verify that required packages are importable."""
    missing = []
    for pkg in ["ultralytics", "cv2", "torch", "numpy"]:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"[ERROR] Missing packages: {', '.join(missing)}")
        print("Install them with: pip install ultralytics opencv-python torch numpy")
        sys.exit(1)

def main():
    check_dependencies()

    import cv2
    from ultralytics import YOLO

    # --- Verify helmet model file ---
    if not HELMET_MODEL_PATH.exists():
        print(f"[ERROR] Helmet model not found: {HELMET_MODEL_PATH}")
        print("\nDownload from Google Drive:")
        print("  https://drive.google.com/drive/folders/1E6vjbpqiOCytXphIZB0OnvG45-WvTkH7?usp=sharing")
        print(f"\nPlace 'last_hardhat_200_epochs.pt' in:\n  {HELMET_MODEL_PATH.parent}")
        sys.exit(1)

    # --- Load helmet model ---
    print(f"[INFO] Loading helmet model: {HELMET_MODEL_PATH}")
    try:
        helmet_model = YOLO(str(HELMET_MODEL_PATH))
    except Exception as e:
        print(f"[ERROR] Failed to load helmet model: {e}")
        sys.exit(1)

    # --- Load face detector (more robust alt2 cascade + profile fallback) ---
    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_alt2.xml"
    )
    profile_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_profileface.xml"
    )
    if face_cascade.empty():
        print("[ERROR] Failed to load face cascade.")
        sys.exit(1)

    print(f"[INFO] Helmet model classes: {helmet_model.names}")
    print(f"[INFO] Face detector: Haar cascade (frontal alt2 + profile)")
    print(f"[INFO] Helmet confidence: {CONFIDENCE_THRESHOLD}")
    print(f"[INFO] Face sensitivity: scaleFactor={FACE_SCALE_FACTOR}, minNeighbors={FACE_MIN_NEIGHBORS}")
    print(f"[INFO] Inference size: {INFERENCE_SIZE}px | Device: cpu")

    # --- Open webcam ---
    print(f"[INFO] Opening webcam (index {WEBCAM_INDEX})...")
    cap = cv2.VideoCapture(WEBCAM_INDEX)
    if not cap.isOpened():
        print("[ERROR] Could not open webcam.")
        sys.exit(1)

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW_NAME, 960, 540)

    # CLAHE for histogram equalization (improves face detection in poor light)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

    print("[INFO] Webcam opened. Press 'q' to quit.")
    print("-" * 55)

    frame_count = 0
    fps_start = time.time()
    # Cached state for skipped frames
    cached_status = "NO PERSON DETECTED"
    cached_faces = []
    cached_helmet_boxes = []

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("[ERROR] Failed to read frame from webcam.")
                break

            frame_count += 1
            run_inference = (frame_count % SKIP_FRAMES == 1) or (SKIP_FRAMES == 1)

            if run_inference:
                try:
                    # --- Face detection (fast, with contrast enhancement) ---
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    gray = clahe.apply(gray)  # Improve contrast for face detection

                    # Try frontal face first
                    faces = face_cascade.detectMultiScale(
                        gray,
                        scaleFactor=FACE_SCALE_FACTOR,
                        minNeighbors=FACE_MIN_NEIGHBORS,
                        minSize=FACE_MIN_SIZE
                    )
                    # If no frontal face, try profile (side face)
                    if len(faces) == 0:
                        faces = profile_cascade.detectMultiScale(
                            gray,
                            scaleFactor=FACE_SCALE_FACTOR,
                            minNeighbors=FACE_MIN_NEIGHBORS,
                            minSize=FACE_MIN_SIZE
                        )
                    cached_faces = faces

                    # --- Helmet detection (always run, independent of face) ---
                    helmet_results = helmet_model(
                        frame, device="cpu", conf=CONFIDENCE_THRESHOLD,
                        imgsz=INFERENCE_SIZE, verbose=False
                    )
                    cached_helmet_boxes = helmet_results[0].boxes

                    # --- Determine status ---
                    helmet_found = len(cached_helmet_boxes) > 0
                    face_found = len(cached_faces) > 0

                    if helmet_found:
                        # Helmet visible = someone is wearing it → compliant
                        cached_status = f"HELMET DETECTED ({len(cached_helmet_boxes)})"
                    elif face_found:
                        # Face visible but no helmet → non-compliant
                        cached_status = "NO HELMET DETECTED"
                    else:
                        # Nothing detected → no one in frame
                        cached_status = "NO PERSON DETECTED"

                except Exception as e:
                    print(f"[ERROR] Inference failed: {e}")
                    break

            # --- Draw bounding boxes ---
            # Face boxes (blue)
            for (x, y, w, h) in cached_faces:
                cv2.rectangle(frame, (x, y), (x + w, y + h), (255, 180, 0), 2)
                text = "face"
                ts = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)[0]
                cv2.rectangle(frame, (x, y - ts[1] - 8), (x + ts[0], y), (255, 180, 0), -1)
                cv2.putText(frame, text, (x, y - 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

            # Helmet boxes (green)
            for box in cached_helmet_boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                conf = float(box.conf[0])
                label = helmet_model.names.get(int(box.cls[0]), "helmet")
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                text = f"{label}: {conf:.2f}"
                ts = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)[0]
                cv2.rectangle(frame, (x1, y1 - ts[1] - 8), (x1 + ts[0], y1), (0, 255, 0), -1)
                cv2.putText(frame, text, (x1, y1 - 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

            # --- Status bar ---
            if "NO PERSON" in cached_status:
                status_color = (0, 200, 255)    # Yellow
            elif "NO HELMET" in cached_status:
                status_color = (0, 0, 255)      # Red
            else:
                status_color = (0, 255, 0)       # Green

            cv2.rectangle(frame, (0, 0), (frame.shape[1], 40), (0, 0, 0), -1)
            cv2.putText(frame, cached_status, (10, 28),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, status_color, 2)

            # FPS counter
            elapsed = time.time() - fps_start
            if elapsed > 0:
                fps = frame_count / elapsed
                cv2.putText(frame, f"FPS: {fps:.1f}", (frame.shape[1] - 130, 28),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

            cv2.imshow(WINDOW_NAME, frame)

            if frame_count % 30 == 0:
                print(f"  Frame {frame_count} | FPS: {fps:.1f} | {cached_status}")

            if cv2.waitKey(1) & 0xFF == ord('q'):
                print("\n[INFO] Quit key pressed.")
                break

    except KeyboardInterrupt:
        print("\n[INFO] Interrupted by user.")
    finally:
        cap.release()
        cv2.destroyAllWindows()
        print("[INFO] Webcam released. Window closed.")
        elapsed = time.time() - fps_start
        if elapsed > 0 and frame_count > 0:
            print(f"[INFO] Processed {frame_count} frames in {elapsed:.1f}s "
                  f"(avg {frame_count/elapsed:.1f} FPS)")

if __name__ == "__main__":
    main()
