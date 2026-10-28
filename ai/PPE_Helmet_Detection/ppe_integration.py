"""
PPE Integration Script — Laptop ↔ ESP32 Communication
Polls the ESP32 /scan endpoint for new RFID scans.
Queries the local SQLite database to determine authorization.
Sends the authorization result to ESP32 /auth_result.
After an authorized scan, waits for a configurable positioning delay
(default 5 s) so the worker can stand in front of the camera.
Runs webcam-based helmet detection with 5-frame majority voting.
Sends the result to the ESP32 /ppe_result endpoint.
Logs all scan events to the local SQLite database.

Part of: AI-Based Smart PPE Compliance Monitoring System (Industrial IoT)

Usage:
  python ppe_integration.py --esp32-ip 192.168.x.x
  python ppe_integration.py --esp32-ip 192.168.x.x --show-camera
  python ppe_integration.py --esp32-ip 192.168.x.x --webcam 1

Detection states sent to ESP32:
  helmet_on          - Worker is wearing a helmet (compliant)
  helmet_off         - Worker is NOT wearing a helmet (non-compliant)
  no_person          - No worker detected in frame (prompt to reposition)
  verification_error - Camera/inference failure (technical problem)

Controls:
  Ctrl+C - Stop the integration script and release webcam
  q      - Quit from camera preview window (when --show-camera is used)
"""

import sys
import time
import argparse
from pathlib import Path
from datetime import datetime

# --- Configuration (matches helmet_webcam_test.py) ---
HELMET_MODEL_PATH = Path(__file__).parent / "models" / "last_hardhat_200_epochs.pt"
CONFIDENCE_THRESHOLD = 0.45   # Same as standalone test
INFERENCE_SIZE = 320          # Same as standalone test
FACE_SCALE_FACTOR = 1.1
FACE_MIN_NEIGHBORS = 3
FACE_MIN_SIZE = (40, 40)

# --- Integration settings ---
VOTE_FRAMES = 5               # Fresh frames for majority voting
POLL_INTERVAL = 1.0           # Seconds between ESP32 polls
HTTP_TIMEOUT = 5              # Seconds for HTTP requests to ESP32
NO_PERSON_RETRIES = 2         # Retry attempts when no person detected
RETRY_DELAY = 3.0             # Seconds between no_person retries
POSITIONING_DELAY_SECONDS = 5 # Seconds to wait after authorized scan
PREVIEW_WINDOW = "PPE Integration - Camera Preview"

# --- Database path (project-relative) ---
# Resolves to: <project_root>/database/ppe_monitor.db
DB_PATH = Path(__file__).parent.parent.parent / "database" / "ppe_monitor.db"


def log(msg):
    """Timestamped console log."""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def check_dependencies():
    """Verify required packages are importable."""
    missing = []
    for pkg in ["ultralytics", "cv2", "torch", "numpy", "requests"]:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"[ERROR] Missing packages: {', '.join(missing)}")
        print("Install: pip install ultralytics opencv-python torch numpy requests")
        sys.exit(1)


def load_models():
    """Load YOLO helmet model and Haar cascade face detectors."""
    import cv2
    from ultralytics import YOLO

    if not HELMET_MODEL_PATH.exists():
        log(f"[ERROR] Helmet model not found: {HELMET_MODEL_PATH}")
        sys.exit(1)

    log(f"Loading helmet model: {HELMET_MODEL_PATH.name}")
    helmet_model = YOLO(str(HELMET_MODEL_PATH))
    log(f"Model classes: {helmet_model.names}")

    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_alt2.xml"
    )
    profile_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_profileface.xml"
    )
    if face_cascade.empty():
        log("[ERROR] Failed to load face cascade")
        sys.exit(1)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    log("Face detectors loaded (frontal alt2 + profile + CLAHE)")

    return helmet_model, face_cascade, profile_cascade, clahe


def detect_single_frame(frame, helmet_model, face_cascade, profile_cascade, clahe):
    """
    Run detection on ONE fresh frame.
    Returns: ('helmet_on'|'helmet_off'|'no_person', faces, helmet_boxes)
    Raises Exception on inference failure (caller handles as verification_error).
    """
    import cv2

    # Face detection (with CLAHE enhancement)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = clahe.apply(gray)

    faces = face_cascade.detectMultiScale(
        gray, scaleFactor=FACE_SCALE_FACTOR,
        minNeighbors=FACE_MIN_NEIGHBORS, minSize=FACE_MIN_SIZE
    )
    if len(faces) == 0:
        faces = profile_cascade.detectMultiScale(
            gray, scaleFactor=FACE_SCALE_FACTOR,
            minNeighbors=FACE_MIN_NEIGHBORS, minSize=FACE_MIN_SIZE
        )

    # Helmet detection (independent of face, same as standalone script)
    results = helmet_model(
        frame, device="cpu", conf=CONFIDENCE_THRESHOLD,
        imgsz=INFERENCE_SIZE, verbose=False
    )
    helmet_boxes = results[0].boxes
    helmet_found = len(helmet_boxes) > 0
    face_found = len(faces) > 0

    # Same three-state logic as helmet_webcam_test.py
    if helmet_found:
        return "helmet_on", faces, helmet_boxes
    elif face_found:
        return "helmet_off", faces, helmet_boxes
    else:
        return "no_person", faces, helmet_boxes


def majority_vote(cap, helmet_model, face_cascade, profile_cascade, clahe,
                  show_camera=False):
    """
    Capture VOTE_FRAMES fresh frames, run inference on EACH frame,
    return the majority result.
    Returns 'verification_error' on camera or inference failure.
    When show_camera is True, updates the preview window with annotations.
    """
    if not cap.isOpened():
        log("  Camera not available")
        return "verification_error"

    votes = []
    for i in range(VOTE_FRAMES):
        ret, frame = cap.read()
        if not ret:
            log(f"  Frame {i+1}/{VOTE_FRAMES}: capture FAILED")
            return "verification_error"

        try:
            result, faces, helmet_boxes = detect_single_frame(
                frame, helmet_model, face_cascade, profile_cascade, clahe
            )
            votes.append(result)
            log(f"  Frame {i+1}/{VOTE_FRAMES}: {result}")

            # Update preview with detection annotations during inference
            if show_camera:
                draw_preview(frame, result, faces, helmet_boxes,
                             helmet_model,
                             f"DETECTING {i+1}/{VOTE_FRAMES}")
        except Exception as e:
            log(f"  Frame {i+1}/{VOTE_FRAMES}: inference ERROR - {e}")
            return "verification_error"

    # Count votes and pick majority
    counts = {}
    for v in votes:
        counts[v] = counts.get(v, 0) + 1

    winner = max(counts, key=counts.get)
    log(f"  Majority vote: {winner} (votes: {counts})")
    return winner


def poll_esp32(esp32_url):
    """
    Poll GET /scan on ESP32. Returns parsed JSON dict or None on error.
    """
    import requests

    try:
        resp = requests.get(f"{esp32_url}/scan", timeout=HTTP_TIMEOUT)
        if resp.status_code == 200:
            return resp.json()
        else:
            log(f"  ESP32 /scan returned {resp.status_code}")
            return None
    except requests.exceptions.ConnectionError:
        log("  ESP32 unreachable (connection refused)")
        return None
    except requests.exceptions.Timeout:
        log("  ESP32 poll timed out")
        return None
    except Exception as e:
        log(f"  ESP32 poll error: {e}")
        return None


def send_auth_result(esp32_url, scan_id, authorized, worker_name=""):
    """
    POST authorization decision to ESP32 /auth_result endpoint.
    Returns True on success, False on failure.
    """
    import requests

    payload = {
        "scan_id": scan_id,
        "authorized": authorized,
        "worker_name": worker_name
    }
    try:
        resp = requests.post(
            f"{esp32_url}/auth_result",
            json=payload,
            timeout=HTTP_TIMEOUT
        )
        if resp.status_code == 200:
            log(f"  ESP32 auth_result accepted: {resp.json()}")
            return True
        elif resp.status_code == 409:
            log(f"  ESP32 auth_result rejected (stale scan): {resp.json()}")
            return False
        else:
            log(f"  ESP32 auth_result returned {resp.status_code}: {resp.text}")
            return False
    except requests.exceptions.ConnectionError:
        log("  ESP32 unreachable for auth_result")
        return False
    except requests.exceptions.Timeout:
        log("  ESP32 auth_result POST timed out")
        return False
    except Exception as e:
        log(f"  ESP32 auth_result POST error: {e}")
        return False


def send_ppe_result(esp32_url, scan_id, status, final=True):
    """
    POST detection result to ESP32 /ppe_result endpoint.
    When final=False, the ESP32 will update its OLED but suppress the buzzer
    (used for interim no_person retries).
    Returns True on success, False on failure.
    """
    import requests

    payload = {"scan_id": scan_id, "status": status, "final": final}
    try:
        resp = requests.post(
            f"{esp32_url}/ppe_result",
            json=payload,
            timeout=HTTP_TIMEOUT
        )
        if resp.status_code == 200:
            log(f"  ESP32 accepted: {resp.json()}")
            return True
        elif resp.status_code == 409:
            log(f"  ESP32 rejected (stale scan): {resp.json()}")
            return False
        else:
            log(f"  ESP32 returned {resp.status_code}: {resp.text}")
            return False
    except requests.exceptions.ConnectionError:
        log("  ESP32 unreachable for PPE result")
        return False
    except requests.exceptions.Timeout:
        log("  ESP32 PPE result POST timed out")
        return False
    except Exception as e:
        log(f"  ESP32 POST error: {e}")
        return False


def draw_preview(frame, status, faces, helmet_boxes, helmet_model, phase=""):
    """
    Draw detection annotations and status on the frame and update the
    preview window. Only called when --show-camera is enabled.
    """
    import cv2

    # Draw face boxes (blue)
    for (x, y, w, h) in faces:
        cv2.rectangle(frame, (x, y), (x + w, y + h), (255, 180, 0), 2)
        cv2.putText(frame, "face", (x, y - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 180, 0), 2)

    # Draw helmet boxes (green)
    for box in helmet_boxes:
        x1, y1, x2, y2 = map(int, box.xyxy[0])
        conf = float(box.conf[0])
        label = helmet_model.names.get(int(box.cls[0]), "helmet")
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(frame, f"{label}: {conf:.2f}", (x1, y1 - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

    # Status bar at top
    status_colors = {
        "helmet_on": (0, 255, 0),
        "helmet_off": (0, 0, 255),
        "no_person": (0, 200, 255),
    }
    color = status_colors.get(status, (200, 200, 200))
    label_text = f"{phase}  |  {status}" if phase else status
    cv2.rectangle(frame, (0, 0), (frame.shape[1], 40), (0, 0, 0), -1)
    cv2.putText(frame, label_text, (10, 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

    cv2.imshow(PREVIEW_WINDOW, frame)
    cv2.waitKey(1)


def positioning_countdown(cap, show_camera=False):
    """
    Non-blocking 5-second countdown that keeps the webcam preview alive.
    Displays a console countdown and an on-screen overlay during the delay.
    Returns True if the countdown completed, False if the user pressed 'q'.
    """
    import cv2

    delay = POSITIONING_DELAY_SECONDS
    log(f"Authorized scan received.")
    log(f"Position yourself in front of the camera: {delay}...")

    start = time.time()
    last_printed = delay  # Track last printed second for console countdown

    while True:
        elapsed = time.time() - start
        remaining = delay - elapsed
        if remaining <= 0:
            break

        current_second = int(remaining)  # Whole seconds remaining

        # Print countdown digits as they change (4... 3... 2... 1...)
        if current_second < last_printed:
            last_printed = current_second
            if current_second > 0:
                log(f"{current_second}...")

        # Keep preview alive
        if cap.isOpened():
            ret, frame = cap.read()
            if ret and show_camera:
                # Draw countdown overlay on camera preview
                cv2.rectangle(frame, (0, 0), (frame.shape[1], 40),
                              (0, 0, 0), -1)
                overlay_text = (f"POSITIONING  |  "
                                f"Get in front of camera: {current_second + 1}s")
                cv2.putText(frame, overlay_text, (10, 28),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                            (0, 200, 255), 2)
                cv2.imshow(PREVIEW_WINDOW, frame)

        # Check for 'q' key — waitKey keeps the window responsive
        if show_camera:
            key = cv2.waitKey(30) & 0xFF
        else:
            # Even without preview, throttle the loop to avoid busy-waiting
            time.sleep(0.03)
            key = 0xFF

        if key == ord('q'):
            log("Quit key pressed during positioning countdown")
            return False

    log("Starting PPE detection...")
    return True


def run_ppe_check(cap, helmet_model, face_cascade, profile_cascade, clahe,
                  esp32_url, scan_id, show_camera=False,
                  db=None, db_row_id=None):
    """
    Run PPE detection with retries for no_person.
    On no_person: sends interim result so OLED shows 'STAND IN VIEW',
    waits for repositioning, then retries.
    Returns the final status string.

    Args:
        db:         PPEDatabase instance (or None to skip logging)
        db_row_id:  Database row ID for the current scan record
    """
    for attempt in range(1 + NO_PERSON_RETRIES):
        attempt_label = f"(attempt {attempt+1}/{1 + NO_PERSON_RETRIES})"

        log(f"Running detection {attempt_label}...")
        result = majority_vote(
            cap, helmet_model, face_cascade, profile_cascade, clahe,
            show_camera=show_camera
        )

        # If verification_error, send immediately and stop
        if result == "verification_error":
            log(f"Verification error {attempt_label} — sending to ESP32")
            send_ppe_result(esp32_url, scan_id, result, final=True)
            # --- Database: mark as FAILED ---
            _db_update_final(db, db_row_id, result, "FAILED", attempt + 1)
            return result

        # If no_person and retries remaining, send INTERIM (final=False)
        # so OLED shows 'STAND IN VIEW' but buzzer does NOT fire
        if result == "no_person" and attempt < NO_PERSON_RETRIES:
            log(f"No person detected {attempt_label}")
            log(f"Sending interim 'no_person' so OLED prompts worker...")
            send_ppe_result(esp32_url, scan_id, "no_person", final=False)
            # --- Database: update attempt count (stay PENDING) ---
            _db_update_attempts(db, db_row_id, attempt + 1)
            log(f"Waiting {RETRY_DELAY}s for worker to reposition...")
            time.sleep(RETRY_DELAY)
            continue

        # Final result (helmet_on, helmet_off, or no_person after all retries)
        log(f"Final result: {result}")
        send_ppe_result(esp32_url, scan_id, result, final=True)
        # --- Database: mark as FINAL ---
        _db_update_final(db, db_row_id, result, "FINAL", attempt + 1)
        return result

    return "verification_error"  # Should not reach here


# ── Database helper wrappers (safe — never crash the main loop) ──

def _db_update_attempts(db, db_row_id, attempts):
    """Update attempt count on the current scan record. Safe no-op if db is None."""
    if db is None or db_row_id is None:
        return
    try:
        db.update_scan_attempts(db_row_id, attempts)
    except Exception as e:
        log(f"[DB WARN] Failed to update attempts: {e}")


def _db_update_final(db, db_row_id, ppe_status, verification_status, attempts):
    """Update the final result on the current scan record. Safe no-op if db is None."""
    if db is None or db_row_id is None:
        return
    try:
        db.update_scan_result(db_row_id, ppe_status,
                              verification_status, attempts)
    except Exception as e:
        log(f"[DB WARN] Failed to update final result: {e}")


def check_authorization(db, uid):
    """
    Query SQLite to determine if a UID is authorized.
    Authorization requires: registered worker AND is_active == 1.

    Args:
        db:  PPEDatabase instance (must not be None)
        uid: Raw RFID UID string from ESP32

    Returns:
        (authorized: bool, worker_name: str or "", worker_id: int or None,
         reason: str)

    Raises:
        Exception if the database query fails (caller must handle).
    """
    from database.db_manager import _normalize_uid

    normalized_uid = _normalize_uid(uid)
    if not normalized_uid:
        return (False, "", None, "invalid_uid")

    worker = db.get_worker_by_uid(normalized_uid)
    if worker is None:
        return (False, "", None, "unknown_uid")
    if not worker.get("is_active", 0):
        return (False, worker["worker_name"], worker["worker_id"],
                "inactive_worker")
    return (True, worker["worker_name"], worker["worker_id"],
            "authorized")


def main():
    check_dependencies()

    import cv2

    parser = argparse.ArgumentParser(
        description="PPE Integration — Laptop ↔ ESP32 Communication"
    )
    parser.add_argument(
        "--esp32-ip", required=True,
        help="ESP32 IP address (e.g., 192.168.1.100)"
    )
    parser.add_argument(
        "--webcam", type=int, default=0,
        help="Webcam index (default: 0)"
    )
    parser.add_argument(
        "--show-camera", action="store_true",
        help="Show live webcam preview window with detection annotations"
    )
    args = parser.parse_args()

    esp32_url = f"http://{args.esp32_ip}"
    show_camera = args.show_camera

    # Load AI models
    log("=" * 50)
    log("PPE Integration Script starting")
    log("=" * 50)
    helmet_model, face_cascade, profile_cascade, clahe = load_models()

    # --- Initialize SQLite database ---
    db = None
    try:
        # Add project root to path so 'database' package is importable
        project_root = Path(__file__).parent.parent.parent
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))
        from database.db_manager import PPEDatabase

        db = PPEDatabase(db_path=DB_PATH)
        if db.initialize_database():
            log(f"Database ready: {DB_PATH.name}")
        else:
            log("[WARN] Database initialization failed — logging disabled")
            db = None
    except Exception as e:
        log(f"[WARN] Database unavailable: {e} — logging disabled")
        db = None

    # Open webcam (kept open between checks)
    log(f"Opening webcam (index {args.webcam})...")
    cap = cv2.VideoCapture(args.webcam)
    if not cap.isOpened():
        log("[ERROR] Cannot open webcam")
        sys.exit(1)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    log("Webcam ready (1280x720)")

    # Open preview window if requested
    if show_camera:
        cv2.namedWindow(PREVIEW_WINDOW, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(PREVIEW_WINDOW, 960, 540)
        log("Camera preview window opened (press 'q' in window to quit)")

    # Verify ESP32 connection
    log(f"Testing ESP32 connection at {esp32_url}...")
    scan_data = poll_esp32(esp32_url)
    if scan_data:
        log(f"ESP32 online: {scan_data.get('device', '?')}")
    else:
        log("[WARN] ESP32 not reachable — will keep retrying")

    log("-" * 50)
    log(f"Polling {esp32_url}/scan every {POLL_INTERVAL}s")
    log(f"Detection: {VOTE_FRAMES}-frame majority vote, "
        f"{NO_PERSON_RETRIES} no_person retries")
    log(f"Camera preview: {'ON' if show_camera else 'OFF'}")
    log(f"Database logging: {'ON' if db else 'OFF'}")
    log(f"Authorization: Dynamic (SQLite workers table)")
    log("Press Ctrl+C to stop")
    log("-" * 50)

    last_processed_scan = 0
    last_denied_scan = 0          # Track last denied scan to avoid duplicates

    try:
        while True:
            # Update camera preview during idle polling
            if show_camera:
                ret, frame = cap.read()
                if ret:
                    # Show live feed with idle status overlay
                    cv2.rectangle(frame, (0, 0), (frame.shape[1], 40),
                                  (0, 0, 0), -1)
                    cv2.putText(frame, "IDLE  |  Waiting for RFID scan...",
                                (10, 28), cv2.FONT_HERSHEY_SIMPLEX,
                                0.7, (200, 200, 200), 2)
                    cv2.imshow(PREVIEW_WINDOW, frame)
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    log("Quit key pressed in preview window")
                    break

            scan_data = poll_esp32(esp32_url)

            if scan_data is not None:
                scan_id = scan_data.get("count", 0)
                access = scan_data.get("access", "")
                ppe = scan_data.get("ppe", "")
                uid = scan_data.get("uid", "?")

                # --- New scan waiting for authorization ---
                if (scan_id > last_processed_scan
                        and scan_id > last_denied_scan
                        and access == "WAITING"):

                    log("=" * 50)
                    log(f"NEW SCAN: #{scan_id} | UID: {uid}")
                    log("=" * 50)

                    # --- Check authorization via SQLite ---
                    if db is None:
                        # Database unavailable — fail closed
                        log("[AUTH] Database unavailable — DENYING access "
                            "(fail closed)")
                        send_auth_result(esp32_url, scan_id,
                                         authorized=False, worker_name="")
                        last_denied_scan = scan_id
                        # Do NOT log to DB since it's unavailable
                        log(f"Scan #{scan_id} denied (no database)")
                        log("-" * 50)
                        continue

                    try:
                        authorized, worker_name, worker_id, reason = \
                            check_authorization(db, uid)
                    except Exception as e:
                        # Database query failed — fail closed
                        log(f"[AUTH] Database query failed: {e} — DENYING "
                            f"access (fail closed)")
                        send_auth_result(esp32_url, scan_id,
                                         authorized=False, worker_name="")
                        last_denied_scan = scan_id
                        log(f"Scan #{scan_id} denied (database error)")
                        log("-" * 50)
                        continue

                    if authorized:
                        log(f"[AUTH] AUTHORIZED — Worker: {worker_name} "
                            f"(ID: {worker_id})")

                        # Send auth result to ESP32 (triggers buzzer + OLED)
                        send_auth_result(esp32_url, scan_id,
                                         authorized=True,
                                         worker_name=worker_name)

                        # --- Database: log authorized scan as PENDING ---
                        db_row_id = None
                        try:
                            db_row_id = db.log_scan(
                                scan_id=scan_id, rfid_uid=uid,
                                access_status="AUTHORIZED",
                                ppe_status=None,
                                verification_status="PENDING"
                            )
                            log(f"DB: Authorized scan #{scan_id} logged "
                                f"(row {db_row_id})")
                        except Exception as e:
                            log(f"[DB WARN] Failed to log scan: {e}")
                            db_row_id = None

                        # --- Positioning delay ---
                        countdown_ok = positioning_countdown(
                            cap, show_camera=show_camera
                        )
                        if not countdown_ok:
                            # User pressed 'q' during countdown — exit cleanly
                            log("Countdown aborted by user")
                            break

                        result = run_ppe_check(
                            cap, helmet_model, face_cascade,
                            profile_cascade, clahe,
                            esp32_url, scan_id,
                            show_camera=show_camera,
                            db=db, db_row_id=db_row_id
                        )

                        last_processed_scan = scan_id
                        log(f"Scan #{scan_id} complete: {result}")
                        log("-" * 50)

                    else:
                        # DENIED — unknown UID or inactive worker
                        log(f"[AUTH] DENIED — Reason: {reason}, "
                            f"UID: {uid}")
                        if worker_name:
                            log(f"[AUTH] Worker: {worker_name} (inactive)")

                        # Send denial to ESP32 (triggers denied buzzer)
                        send_auth_result(esp32_url, scan_id,
                                         authorized=False,
                                         worker_name=worker_name)

                        last_denied_scan = scan_id

                        # --- Database: log denied scan ---
                        try:
                            db.log_scan(
                                scan_id=scan_id, rfid_uid=uid,
                                access_status="DENIED",
                                ppe_status=None,
                                verification_status="DENIED"
                            )
                            log(f"DB: Denied scan #{scan_id} logged")
                        except Exception as e:
                            log(f"[DB WARN] Failed to log denied scan: {e}")

                        log(f"Scan #{scan_id} denied — no PPE check")
                        log("-" * 50)

            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        log("\nInterrupted by user")
    finally:
        cap.release()
        if show_camera:
            cv2.destroyAllWindows()
        log("Webcam released. Exiting.")


if __name__ == "__main__":
    main()
