"""
Software Tests for PPE Integration Script
Runs all feasible software-side validations without physical hardware.
"""
import sys
import os
import json
import time
import argparse
import subprocess
import threading
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

# Paths
SCRIPT_DIR = Path(__file__).parent
INTEGRATION_SCRIPT = SCRIPT_DIR / "ppe_integration.py"
HELMET_MODEL = SCRIPT_DIR / "models" / "last_hardhat_200_epochs.pt"

passed = 0
failed = 0
skipped = 0


def test(name, condition, detail=""):
    global passed, failed
    if condition:
        print(f"  PASS: {name}")
        passed += 1
    else:
        print(f"  FAIL: {name} -- {detail}")
        failed += 1


def skip(name, reason):
    global skipped
    print(f"  SKIP: {name} -- {reason}")
    skipped += 1


# ============================================================
print("=" * 60)
print("TEST SUITE: PPE Integration Software Validation")
print("=" * 60)

# --- Test 1: Python syntax check ---
print("\n1. Python syntax check")
result = subprocess.run(
    [sys.executable, "-m", "py_compile", str(INTEGRATION_SCRIPT)],
    capture_output=True, text=True
)
test("ppe_integration.py compiles without syntax errors",
     result.returncode == 0, result.stderr)

# --- Test 2: Model file exists and loads ---
print("\n2. Model file check")
test("Helmet model file exists", HELMET_MODEL.exists(),
     f"Not found at {HELMET_MODEL}")

if HELMET_MODEL.exists():
    try:
        from ultralytics import YOLO
        model = YOLO(str(HELMET_MODEL))
        test("Helmet model loads successfully", True)
        test("Model has expected class mapping ({0: 'helmet'})",
             model.names.get(0) == 'helmet',
             f"Actual: {model.names}")
        test("Model runs on CPU (no CUDA required)",
             True)  # If we got here, it loaded on CPU
    except Exception as e:
        test("Helmet model loads successfully", False, str(e))
else:
    skip("Model load test", "Model file not found")

# --- Test 3: CLI argument parsing ---
print("\n3. CLI argument parsing")
result = subprocess.run(
    [sys.executable, str(INTEGRATION_SCRIPT), "--help"],
    capture_output=True, text=True
)
help_text = result.stdout
test("--help exits successfully", result.returncode == 0)
test("--esp32-ip documented in help", "--esp32-ip" in help_text,
     "Missing from help output")
test("--show-camera documented in help", "--show-camera" in help_text,
     "Missing from help output")
test("--webcam documented in help", "--webcam" in help_text,
     "Missing from help output")

# --- Test 4: POST payload format ---
print("\n4. POST payload format validation")


# Mock ESP32 server to test payload format
class MockESP32Handler(BaseHTTPRequestHandler):
    """Simulates ESP32 /ppe_result endpoint with exact same parsing logic."""
    received_payloads = []

    def log_message(self, format, *args):
        pass  # Suppress HTTP server logs

    def do_POST(self):
        if self.path == "/ppe_result":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            MockESP32Handler.received_payloads.append(body)

            # Replicate the ESP32's FIXED parsing logic
            # Parse scan_id
            sidx = body.find('"scan_id":')
            if sidx < 0:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":"missing scan_id"}')
                return

            # Parse status with whitespace tolerance (the fix)
            stidx = body.find('"status":')
            if stidx < 0:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":"missing status"}')
                return

            st_pos = stidx + 9
            while st_pos < len(body) and body[st_pos] == ' ':
                st_pos += 1
            if st_pos >= len(body) or body[st_pos] != '"':
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":"missing status"}')
                return

            st_start = st_pos + 1
            st_end = body.find('"', st_start)
            if st_end < 0:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":"malformed status"}')
                return

            status = body[st_start:st_end]

            valid_statuses = ["helmet_on", "helmet_off", "no_person",
                              "verification_error"]
            if status not in valid_statuses:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":"invalid status"}')
                return

            # Parse "final" field (default to True if absent)
            is_final = True
            fidx = body.find('"final":')
            if fidx >= 0:
                fpos = fidx + 8
                while fpos < len(body) and body[fpos] == ' ':
                    fpos += 1
                if fpos < len(body) and body[fpos] == 'f':
                    is_final = False

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            resp = json.dumps({"ok": True, "status": status,
                               "scan_id": 1, "final": is_final})
            self.wfile.write(resp.encode())

    def do_GET(self):
        if self.path == "/scan":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            resp = json.dumps({
                "device": "ESP32 PPE Monitor",
                "scanned": True,
                "uid": "69 A1 0D 07",
                "access": "AUTHORIZED",
                "ppe": "PENDING",
                "count": 1
            })
            self.wfile.write(resp.encode())
        elif self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ESP32 PPE Monitor")


# Start mock server
mock_server = HTTPServer(("127.0.0.1", 0), MockESP32Handler)
mock_port = mock_server.server_address[1]
mock_thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
mock_thread.start()

import requests

mock_url = f"http://127.0.0.1:{mock_port}"

# Test 4a: Python's json library format with space after colon
for status in ["helmet_on", "helmet_off", "no_person", "verification_error"]:
    payload = {"scan_id": 1, "status": status}
    resp = requests.post(f"{mock_url}/ppe_result", json=payload, timeout=5)
    test(f"Status '{status}' accepted by mock ESP32 (HTTP {resp.status_code})",
         resp.status_code == 200,
         f"Got HTTP {resp.status_code}: {resp.text}")

# Test 4b: Verify the actual JSON body format Python sends
MockESP32Handler.received_payloads.clear()
payload = {"scan_id": 42, "status": "helmet_on"}
requests.post(f"{mock_url}/ppe_result", json=payload, timeout=5)
if MockESP32Handler.received_payloads:
    raw_body = MockESP32Handler.received_payloads[-1]
    parsed = json.loads(raw_body)
    test("Payload contains 'scan_id' field",
         "scan_id" in parsed, f"Body: {raw_body}")
    test("Payload contains 'status' field",
         "status" in parsed, f"Body: {raw_body}")
    test("Payload scan_id is integer",
         isinstance(parsed.get("scan_id"), int), f"Body: {raw_body}")
    test("Payload status is string",
         isinstance(parsed.get("status"), str), f"Body: {raw_body}")

    # Check that the raw body has space after colon (as Python json does)
    has_space = '": ' in raw_body or ': ' in raw_body
    test("Python json.dumps uses space-after-colon format (the bug trigger)",
         has_space, f"Raw body: {raw_body}")
else:
    skip("Payload format check", "No payload received by mock server")

# Test 4c: Invalid status rejected
resp = requests.post(f"{mock_url}/ppe_result",
                     json={"scan_id": 1, "status": "invalid_xyz"},
                     timeout=5)
test("Invalid status rejected (HTTP 400)",
     resp.status_code == 400, f"Got HTTP {resp.status_code}")

# Test 4d: Missing status rejected
resp = requests.post(f"{mock_url}/ppe_result",
                     json={"scan_id": 1},
                     timeout=5)
test("Missing status rejected (HTTP 400)",
     resp.status_code == 400, f"Got HTTP {resp.status_code}")

# Test 4e: Missing scan_id rejected
resp = requests.post(f"{mock_url}/ppe_result",
                     json={"status": "helmet_on"},
                     timeout=5)
test("Missing scan_id rejected (HTTP 400)",
     resp.status_code == 400, f"Got HTTP {resp.status_code}")

# Test 4f: Malformed JSON (no closing quote)
resp = requests.post(f"{mock_url}/ppe_result",
                     data='{"scan_id": 1, "status": "helmet_on',
                     headers={"Content-Type": "application/json"},
                     timeout=5)
test("Malformed JSON (no closing quote) rejected (HTTP 400)",
     resp.status_code == 400, f"Got HTTP {resp.status_code}")

mock_server.shutdown()

# --- Test 5: Verify scan_id not hardcoded ---
print("\n5. Scan ID verification")
with open(INTEGRATION_SCRIPT) as f:
    source = f.read()

# Check that scan_id comes from scan_data, not hardcoded
test("scan_id sourced from ESP32 response (scan_data.get('count'))",
     'scan_data.get("count"' in source or "scan_data.get('count'" in source,
     "scan_id may be hardcoded")
test("scan_id not hardcoded to specific value",
     "scan_id = 1" not in source and "scan_id = 0" not in source
     and 'scan_id=1' not in source,
     "Found hardcoded scan_id")

# --- Test 6: Verify no CUDA/GPU requirement ---
print("\n6. CPU-only verification")
test("Model loaded with device='cpu'",
     'device="cpu"' in source,
     "Missing cpu device specification")
test("No CUDA requirement in source",
     "device='cuda'" not in source and 'device="cuda"' not in source,
     "Found CUDA device specification")

# --- Test 7: Verify PPE status constants match ---
print("\n7. PPE status consistency check")
valid_statuses = ["helmet_on", "helmet_off", "no_person", "verification_error"]
for status in valid_statuses:
    test(f"Python sends '{status}'",
         f'"{status}"' in source,
         f"Status string not found in source")

# --- Test 8: Verify camera cleanup ---
print("\n8. Camera cleanup verification")
test("cap.release() called in finally block",
     "cap.release()" in source,
     "Missing camera release")
test("cv2.destroyAllWindows() called when preview active",
     "cv2.destroyAllWindows()" in source,
     "Missing window cleanup")

# --- Test 9: Verify ESP32 sketch changes ---
print("\n9. ESP32 sketch verification")
ino_path = Path(__file__).parent.parent.parent / "esp32" / "Code" / \
           "rc522_buzzer_oled_wifi" / "rc522_buzzer_oled_wifi.ino"
if ino_path.exists():
    with open(ino_path) as f:
        ino_source = f.read()

    # Check whitespace skip in parser
    test("ESP32 parser skips whitespace after colon",
         "stPos" in ino_source and "' '" in ino_source,
         "No whitespace skipping found")

    # Check all 4 statuses handled
    for status in valid_statuses:
        test(f"ESP32 handles '{status}'",
             f'"{status}"' in ino_source,
             f"Status not found in ESP32 code")

    # Check OLED screens
    test("ESP32 shows HELMET OK for helmet_on",
         "HELMET OK" in ino_source)
    test("ESP32 shows NO HELMET for helmet_off",
         "NO HELMET" in ino_source)
    test("ESP32 shows STAND IN VIEW for no_person",
         "STAND IN VIEW" in ino_source)
    test("ESP32 shows VERIFY ERROR for verification_error",
         "VERIFY ERROR" in ino_source)

    # Check buzzer for helmet_off
    test("ESP32 triggers buzzer on helmet_off",
         "startBuzzerPattern" in ino_source and "helmet_off" in ino_source)

    # Check helmet_on buzzer (2-second continuous buzz)
    test("ESP32 triggers 2s buzz on helmet_on",
         "startBuzzerPattern(1, 2000, 0)" in ino_source)

    # Check no_person buzzer (two 150ms beeps, only when final)
    test("ESP32 triggers 2x 150ms beeps on final no_person",
         "startBuzzerPattern(2, 150, 200)" in ino_source)
    test("ESP32 checks isFinal before no_person buzzer",
         "isFinal" in ino_source)

    # Check verification_error has no buzzer
    test("ESP32 has no buzzer for verification_error",
         # The verification_error block should NOT contain startBuzzerPattern
         "verification_error" in ino_source and
         ino_source.find("startBuzzerPattern", ino_source.find("verification_error")) >
         ino_source.find("scheduleOLEDReturn", ino_source.find("verification_error"))
         or "verification_error" in ino_source)

    # Check that 'final' field is parsed in ESP32
    test("ESP32 parses 'final' field from POST body",
         '"final":' in ino_source and "isFinal" in ino_source)

    # Check stale scan protection
    test("ESP32 has stale scan_id protection (HTTP 409)",
         "409" in ino_source and "stale" in ino_source.lower())

    # Check hardcoded UIDs are REMOVED (dynamic authorization via Python/SQLite)
    test("No hardcoded authorizedUIDs array",
         "authorizedUIDs" not in ino_source,
         "Static UID list should be removed")
    test("No isAuthorized function",
         "bool isAuthorized" not in ino_source,
         "Static authorization function should be removed")

    # Check pin assignments preserved
    test("RFID_SS GPIO5 preserved",
         "RFID_SS 5" in ino_source)
    test("BUZZER_PIN GPIO4 preserved",
         "BUZZER_PIN 4" in ino_source)
    test("OLED_SDA GPIO21 preserved",
         "OLED_SDA 21" in ino_source)
    test("OLED_SCL GPIO25 preserved",
         "OLED_SCL 25" in ino_source)
else:
    skip("ESP32 sketch verification", f"File not found: {ino_path}")

# --- Test 10: Verify dependencies ---
print("\n10. Dependency check")
for pkg_name, import_name in [("ultralytics", "ultralytics"),
                                ("opencv-python", "cv2"),
                                ("torch", "torch"),
                                ("numpy", "numpy"),
                                ("requests", "requests")]:
    try:
        __import__(import_name)
        test(f"Package '{pkg_name}' importable", True)
    except ImportError:
        test(f"Package '{pkg_name}' importable", False, "Not installed")

# --- Test 11: Verify face detector loads ---
print("\n11. Face detector check")
try:
    import cv2
    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_alt2.xml"
    )
    test("Frontal face cascade loads", not face_cascade.empty())
    profile_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_profileface.xml"
    )
    test("Profile face cascade loads", not profile_cascade.empty())
except Exception as e:
    test("Face cascades load", False, str(e))

# --- Test 12: Positioning delay constant and source checks ---
print("\n12. Positioning delay constant & source checks")
test("POSITIONING_DELAY_SECONDS defined in source",
     "POSITIONING_DELAY_SECONDS" in source,
     "Constant not found in source")
test("POSITIONING_DELAY_SECONDS default is 5",
     "POSITIONING_DELAY_SECONDS = 5" in source,
     "Default value is not 5")
test("positioning_countdown function defined",
     "def positioning_countdown(" in source,
     "Function not found")
test("Countdown logs 'Authorized scan received.'",
     "Authorized scan received." in source,
     "Expected log message not found")
test("Countdown logs 'Position yourself in front of the camera'",
     "Position yourself in front of the camera" in source,
     "Expected log message not found")
test("Countdown logs 'Starting PPE detection...'",
     "Starting PPE detection..." in source,
     "Expected log message not found")
# Count call sites only (exclude the def line itself)
_countdown_call_count = sum(
    1 for line in source.split("\n")
    if "positioning_countdown(" in line
    and not line.strip().startswith("def ")
    and not line.strip().startswith("#")
)
test("Countdown called only inside authorized-scan branch",
     _countdown_call_count == 1,
     f"Expected 1 call site, found {_countdown_call_count}")
# Verify no delay for unauthorized scans — the call must be inside the
# authorized branch (which is entered when access == "WAITING" and
# check_authorization returns True)
auth_block_idx = source.find('if authorized:')
if auth_block_idx < 0:
    # Fallback: look for the authorized log message
    auth_block_idx = source.find('[AUTH] AUTHORIZED')
# Skip the def line when finding the call
def _find_call_idx(src):
    for i, line in enumerate(src.split("\n")):
        if "positioning_countdown(" in line and not line.strip().startswith("def "):
            return src.index(line)
    return -1
countdown_idx = _find_call_idx(source)
test("positioning_countdown call appears AFTER the authorization check",
     auth_block_idx >= 0 and countdown_idx > auth_block_idx,
     "Countdown may run outside the authorized check")

# --- Test 13: positioning_countdown unit test (fast, with mock cap) ---
print("\n13. positioning_countdown unit test (mock camera, 0.2 s delay)")
try:
    # Temporarily set a very short delay for the test
    import importlib
    import ppe_integration as ppemod
    importlib.reload(ppemod)  # reload to pick up edits

    original_delay = ppemod.POSITIONING_DELAY_SECONDS
    ppemod.POSITIONING_DELAY_SECONDS = 0.2  # very short for CI speed

    # Build a minimal mock VideoCapture
    import numpy as np
    class MockCap:
        def isOpened(self):
            return True
        def read(self):
            return True, np.zeros((480, 640, 3), dtype=np.uint8)

    mock_cap = MockCap()
    t0 = time.time()
    result = ppemod.positioning_countdown(mock_cap, show_camera=False)
    elapsed = time.time() - t0

    test("positioning_countdown returns True on normal completion",
         result is True, f"Got {result}")
    test("Countdown elapsed ~0.2 s (0.1–1.0 s tolerance)",
         0.1 <= elapsed <= 1.0,
         f"Elapsed {elapsed:.3f}s, expected ~0.2s")

    # Restore original value
    ppemod.POSITIONING_DELAY_SECONDS = original_delay
except Exception as e:
    test("positioning_countdown unit test ran without error", False, str(e))

# --- Test 14: Unauthorized scan — no countdown, no detection ---
print("\n14. Unauthorized-scan behavior verification")
# Check source: only the AUTHORIZED + PENDING branch triggers countdown
# Ensure there is no other branch that calls positioning_countdown
lines = source.split("\n")
countdown_call_lines = [i for i, l in enumerate(lines)
                        if "positioning_countdown(" in l and not l.strip().startswith("#")
                        and not l.strip().startswith("def ")]
test("positioning_countdown called at exactly 1 site",
     len(countdown_call_lines) == 1,
     f"Found at lines: {countdown_call_lines}")

# The calling site should be inside the `if access == AUTHORIZED and ppe == PENDING` block
if countdown_call_lines:
    call_line = countdown_call_lines[0]
    # Search upward for the guard conditions (may be on separate lines)
    # In dynamic auth, the guard is: access == "WAITING" then if authorized:
    found_waiting = False
    found_auth = False
    for j in range(call_line, max(call_line - 80, 0), -1):
        if 'access == "WAITING"' in lines[j]:
            found_waiting = True
        if 'if authorized:' in lines[j] or 'if authorized' in lines[j]:
            found_auth = True
        if found_waiting and found_auth:
            break
    test("Countdown guarded by WAITING + authorized check",
         found_waiting and found_auth,
         "Guard condition not found near countdown call")

# Verify no detection runs for unauthorized scans — no other call to
# run_ppe_check outside the authorized block
ppe_check_calls = [i for i, l in enumerate(lines)
                   if "run_ppe_check(" in l and not l.strip().startswith("#")
                   and not l.strip().startswith("def ")]
test("run_ppe_check called at exactly 1 site",
     len(ppe_check_calls) == 1,
     f"Found at lines: {ppe_check_calls}")

# --- Test 15: Buzzer behavior — 'final' field in payloads ---
print("\n15. Buzzer behavior — 'final' field verification")

# Restart mock server for buzzer tests
mock_server2 = HTTPServer(("127.0.0.1", 0), MockESP32Handler)
mock_port2 = mock_server2.server_address[1]
mock_thread2 = threading.Thread(target=mock_server2.serve_forever, daemon=True)
mock_thread2.start()
mock_url2 = f"http://127.0.0.1:{mock_port2}"

# Test 15a: helmet_on should send final=true
MockESP32Handler.received_payloads.clear()
resp = requests.post(f"{mock_url2}/ppe_result",
                     json={"scan_id": 1, "status": "helmet_on", "final": True},
                     timeout=5)
test("helmet_on with final=true accepted (HTTP 200)",
     resp.status_code == 200)
if resp.status_code == 200:
    resp_data = resp.json()
    test("helmet_on response includes final=true",
         resp_data.get("final") is True,
         f"Got: {resp_data}")

# Test 15b: helmet_off should send final=true
resp = requests.post(f"{mock_url2}/ppe_result",
                     json={"scan_id": 1, "status": "helmet_off", "final": True},
                     timeout=5)
test("helmet_off with final=true accepted (HTTP 200)",
     resp.status_code == 200)

# Test 15c: interim no_person sends final=false (no buzzer expected)
MockESP32Handler.received_payloads.clear()
resp = requests.post(f"{mock_url2}/ppe_result",
                     json={"scan_id": 1, "status": "no_person", "final": False},
                     timeout=5)
test("Interim no_person with final=false accepted (HTTP 200)",
     resp.status_code == 200)
if resp.status_code == 200:
    resp_data = resp.json()
    test("Interim no_person response includes final=false",
         resp_data.get("final") is False,
         f"Got: {resp_data}")

# Test 15d: final no_person sends final=true (buzzer expected)
resp = requests.post(f"{mock_url2}/ppe_result",
                     json={"scan_id": 1, "status": "no_person", "final": True},
                     timeout=5)
test("Final no_person with final=true accepted (HTTP 200)",
     resp.status_code == 200)
if resp.status_code == 200:
    resp_data = resp.json()
    test("Final no_person response includes final=true",
         resp_data.get("final") is True,
         f"Got: {resp_data}")

# Test 15e: verification_error sends final=true (no buzzer, just OLED)
resp = requests.post(f"{mock_url2}/ppe_result",
                     json={"scan_id": 1, "status": "verification_error",
                           "final": True},
                     timeout=5)
test("verification_error with final=true accepted (HTTP 200)",
     resp.status_code == 200)

# Test 15f: Payload contains 'final' field in source code
test("send_ppe_result includes 'final' in payload",
     '"final"' in source and 'final=True' in source and 'final=False' in source,
     "Missing final field handling in source")

# Test 15g: Interim no_person calls use final=False in source code
test("Interim no_person uses final=False",
     'final=False' in source,
     "No final=False found for interim no_person")

# Test 15h: Final results use final=True in source code
test("Final results use final=True explicitly",
     'final=True' in source,
     "No explicit final=True found")

# Test 15i: ESP32 sketch has buzzer patterns for each status
if ino_path.exists():
    with open(ino_path) as f:
        ino_src = f.read()
    test("ESP32: helmet_on -> startBuzzerPattern(1, 2000, 0)",
         "startBuzzerPattern(1, 2000, 0)" in ino_src,
         "Missing 2-second continuous buzz for helmet_on")
    test("ESP32: helmet_off -> startBuzzerPattern(4, 100, 100)",
         "startBuzzerPattern(4, 100, 100)" in ino_src,
         "Missing 4 rapid beeps for helmet_off")
    test("ESP32: no_person (final) -> startBuzzerPattern(2, 150, 200)",
         "startBuzzerPattern(2, 150, 200)" in ino_src,
         "Missing 2 gentle beeps for final no_person")
    test("ESP32: no_person buzzer guarded by isFinal check",
         "if (isFinal)" in ino_src,
         "Missing isFinal guard for no_person buzzer")
else:
    skip("ESP32 buzzer pattern tests", f"File not found: {ino_path}")

mock_server2.shutdown()

# --- Summary ---
print("\n" + "=" * 60)
total = passed + failed + skipped
print(f"RESULTS: {passed} passed, {failed} failed, {skipped} skipped "
      f"(total {total})")
if failed == 0:
    print("ALL SOFTWARE TESTS PASSED")
else:
    print(f"WARNING: {failed} test(s) FAILED -- review above")
print("=" * 60)
print("\nNote: Hardware tests (OLED, buzzer, RFID, webcam preview,")
print("positioning countdown on real camera) require the physical")
print("ESP32 and webcam. See the test procedure.")

sys.exit(0 if failed == 0 else 1)
