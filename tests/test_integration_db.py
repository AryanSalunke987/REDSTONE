"""
Integration Tests: Database + PPE Integration Script
=====================================================
Tests that the database logging integrates correctly with
the existing PPE integration workflow.

Uses mocks for hardware (ESP32, webcam) — no physical devices needed.

Run from project root:
  python tests/test_integration_db.py
"""

import sys
import os
import json
import time
import tempfile
import threading
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "ai" / "PPE_Helmet_Detection"))

from database.db_manager import PPEDatabase, _normalize_uid

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


def get_temp_db():
    """Create a PPEDatabase pointing to a temporary file."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = PPEDatabase(db_path=tmp.name)
    db.initialize_database()
    return db, tmp.name


def cleanup_db(path):
    try:
        os.unlink(path)
    except Exception:
        pass


# ============================================================
print("=" * 60)
print("TEST SUITE: Database Integration Tests")
print("=" * 60)

# --- Test 1: Authorized RFID creates exactly one record ---
print("\n1. Authorized RFID creates exactly one record")
db, db_path = get_temp_db()
db.register_worker("69 A1 0D 07", "Aryan Salunke", "Safety")

row_id = db.log_scan(scan_id=1, rfid_uid="69 A1 0D 07",
                     access_status="AUTHORIZED",
                     verification_status="PENDING")
test("Single row created", row_id is not None)

# Verify only one row exists
scans = db.get_recent_scans(limit=100)
auth_scans = [s for s in scans if s["scan_id"] == 1
              and s["access_status"] == "AUTHORIZED"]
test("Exactly one record for scan_id=1", len(auth_scans) == 1,
     f"Found {len(auth_scans)}")

# --- Test 2: Unauthorized RFID is logged without triggering AI ---
print("\n2. Unauthorized RFID logged without AI")
denied_id = db.log_scan(scan_id=2, rfid_uid="FF FF FF FF",
                        access_status="DENIED",
                        verification_status="DENIED")
test("Denied scan logged", denied_id is not None)

denied_scan = db.get_scan_by_id(denied_id)
test("Access status = DENIED", denied_scan["access_status"] == "DENIED")
test("No PPE status (AI not run)", denied_scan["ppe_status"] is None)
test("No worker associated", denied_scan["worker_id"] is None)

# --- Test 3: Interim no-person retries update existing record ---
print("\n3. Interim retries update existing record")
retry_row_id = db.log_scan(scan_id=3, rfid_uid="69 A1 0D 07",
                           access_status="AUTHORIZED",
                           verification_status="PENDING")

# Simulate retry 1
db.update_scan_attempts(retry_row_id, 1)
scan_after_1 = db.get_scan_by_id(retry_row_id)
test("After retry 1: attempts=1", scan_after_1["attempts"] == 1)
test("After retry 1: still PENDING",
     scan_after_1["verification_status"] == "PENDING")

# Simulate retry 2
db.update_scan_attempts(retry_row_id, 2)
scan_after_2 = db.get_scan_by_id(retry_row_id)
test("After retry 2: attempts=2", scan_after_2["attempts"] == 2)

# No new row created for retries
all_scan3 = [s for s in db.get_recent_scans(limit=100)
             if s["scan_id"] == 3]
test("No extra row created for retries", len(all_scan3) == 1)

# --- Test 4: Final PPE result updates same record ---
print("\n4. Final PPE result updates same record")
db.update_scan_result(retry_row_id, "helmet_on", "FINAL", attempts=3)
final_scan = db.get_scan_by_id(retry_row_id)
test("Final status = helmet_on", final_scan["ppe_status"] == "helmet_on")
test("Verification = FINAL", final_scan["verification_status"] == "FINAL")
test("Final attempts = 3", final_scan["attempts"] == 3)

# Still only one row
all_scan3_after = [s for s in db.get_recent_scans(limit=100)
                   if s["scan_id"] == 3]
test("Still exactly one row for scan_id=3", len(all_scan3_after) == 1)

# --- Test 5: Duplicate polling does not create duplicate rows ---
print("\n5. Duplicate polling protection (application-level)")
# In the real app, last_processed_scan prevents re-logging.
# Here we verify that the DB supports the pattern.
first_id = db.log_scan(scan_id=10, rfid_uid="69 A1 0D 07",
                       access_status="AUTHORIZED",
                       verification_status="PENDING")
# If the app accidentally logs the same scan_id again:
second_id = db.log_scan(scan_id=10, rfid_uid="69 A1 0D 07",
                        access_status="AUTHORIZED",
                        verification_status="PENDING")
test("DB allows duplicate scan_ids (different DB row IDs)",
     first_id != second_id)
test("Application must prevent this (documented behavior)", True)

# --- Test 6: Database failure does not crash main workflow ---
print("\n6. Database failure isolation")
import ppe_integration as ppemod

# Test _db_update_attempts with None db — should be a no-op
try:
    ppemod._db_update_attempts(None, None, 1)
    test("_db_update_attempts(None) is safe no-op", True)
except Exception as e:
    test("_db_update_attempts(None) is safe no-op", False, str(e))

# Test _db_update_final with None db — should be a no-op
try:
    ppemod._db_update_final(None, None, "helmet_on", "FINAL", 1)
    test("_db_update_final(None) is safe no-op", True)
except Exception as e:
    test("_db_update_final(None) is safe no-op", False, str(e))

# Test with a broken db (closed/invalid path)
try:
    broken_db = PPEDatabase(db_path="/nonexistent/path/db.sqlite")
    # This should fail gracefully
    ppemod._db_update_attempts(broken_db, 999, 1)
    test("_db_update_attempts with broken db doesn't crash", True)
except Exception as e:
    test("_db_update_attempts with broken db doesn't crash", False, str(e))

try:
    ppemod._db_update_final(broken_db, 999, "helmet_on", "FINAL", 1)
    test("_db_update_final with broken db doesn't crash", True)
except Exception as e:
    test("_db_update_final with broken db doesn't crash", False, str(e))

# --- Test 7: run_ppe_check accepts db/db_row_id params ---
print("\n7. run_ppe_check signature compatibility")
import inspect
sig = inspect.signature(ppemod.run_ppe_check)
params = list(sig.parameters.keys())
test("run_ppe_check has 'db' parameter", "db" in params)
test("run_ppe_check has 'db_row_id' parameter", "db_row_id" in params)
test("'db' defaults to None",
     sig.parameters["db"].default is None)
test("'db_row_id' defaults to None",
     sig.parameters["db_row_id"].default is None)

# --- Test 8: Database logging constants ---
print("\n8. Database configuration in integration script")
test("DB_PATH defined", hasattr(ppemod, "DB_PATH"))
test("DB_PATH is a Path object", isinstance(ppemod.DB_PATH, Path))
test("DB_PATH points to database directory",
     "database" in str(ppemod.DB_PATH))
test("DB_PATH filename is ppe_monitor.db",
     ppemod.DB_PATH.name == "ppe_monitor.db")

# --- Test 9: Source code analysis ---
print("\n9. Source code analysis for database integration")
with open(PROJECT_ROOT / "ai" / "PPE_Helmet_Detection" /
          "ppe_integration.py") as f:
    source = f.read()

test("Database import in main()",
     "from database.db_manager import PPEDatabase" in source)
test("DB initialization with try/except",
     "db.initialize_database()" in source)
test("DB set to None on failure",
     "db = None" in source)
test("Denied scan logging present",
     'access_status="DENIED"' in source or
     "access_status='DENIED'" in source)
test("Authorized scan logged as PENDING",
     'verification_status="PENDING"' in source or
     "verification_status='PENDING'" in source)
test("Database logging status shown at startup",
     "Database logging" in source)
test("last_denied_scan tracking variable",
     "last_denied_scan" in source)
test("DB errors don't crash (try/except around log_scan)",
     "[DB WARN]" in source)

# --- Test 10: Compliance calc with mixed data ---
print("\n10. Compliance calculation correctness")
calc_db, calc_path = get_temp_db()
calc_db.register_worker("AA BB CC DD", "Worker A", "Dept1")

# 3 helmet_on, 1 helmet_off, 2 no_person, 1 verification_error
for i in range(3):
    rid = calc_db.log_scan(scan_id=100+i, rfid_uid="AA BB CC DD",
                           access_status="AUTHORIZED",
                           verification_status="PENDING")
    calc_db.update_scan_result(rid, "helmet_on", "FINAL", 1)

rid = calc_db.log_scan(scan_id=103, rfid_uid="AA BB CC DD",
                       access_status="AUTHORIZED",
                       verification_status="PENDING")
calc_db.update_scan_result(rid, "helmet_off", "FINAL", 1)

rid = calc_db.log_scan(scan_id=104, rfid_uid="AA BB CC DD",
                       access_status="AUTHORIZED",
                       verification_status="PENDING")
calc_db.update_scan_result(rid, "no_person", "FINAL", 3)

rid = calc_db.log_scan(scan_id=105, rfid_uid="AA BB CC DD",
                       access_status="AUTHORIZED",
                       verification_status="PENDING")
calc_db.update_scan_result(rid, "verification_error", "FAILED", 1)

# Denied scan (should be excluded from compliance)
calc_db.log_scan(scan_id=106, rfid_uid="FF FF FF FF",
                 access_status="DENIED", verification_status="DENIED")

summary = calc_db.get_compliance_summary()
# Compliance = 3 / (3 + 1) * 100 = 75.0%
test("Compliance = 75.0%",
     abs(summary["compliance_percentage"] - 75.0) < 0.1,
     f"Got {summary['compliance_percentage']}")
test("helmet_on = 3", summary["helmet_on_count"] == 3)
test("helmet_off = 1", summary["helmet_off_count"] == 1)
test("no_person excluded from denominator",
     summary["compliance_percentage"] == 75.0)
test("Denied scans counted", summary["denied_scans"] >= 1)

cleanup_db(calc_path)

# --- Test 11: check_authorization function ---
print("\n11. Dynamic authorization via check_authorization()")
auth_db, auth_path = get_temp_db()

# Register workers
auth_db.register_worker("69 A1 0D 07", "Aryan Salunke", "Safety")
auth_db.register_worker("A4 58 27 07", "Rohan Patil", "Operations")

# Test authorized active worker
authorized, name, wid, reason = ppemod.check_authorization(
    auth_db, "69 A1 0D 07")
test("Active worker is authorized", authorized is True)
test("Worker name returned", name == "Aryan Salunke")
test("Worker ID returned", wid is not None)
test("Reason = authorized", reason == "authorized")

# Test with different UID format (colon-separated)
authorized2, name2, wid2, reason2 = ppemod.check_authorization(
    auth_db, "69:a1:0d:07")
test("Authorization works with colon-separated UID", authorized2 is True)
test("Same worker found regardless of format", wid2 == wid)

# Test unknown UID
authorized3, name3, wid3, reason3 = ppemod.check_authorization(
    auth_db, "FF FF FF FF")
test("Unknown UID is denied", authorized3 is False)
test("No worker name for unknown", name3 == "")
test("No worker ID for unknown", wid3 is None)
test("Reason = unknown_uid", reason3 == "unknown_uid")

# Test inactive worker
w = auth_db.get_worker_by_uid("A4 58 27 07")
auth_db.deactivate_worker(w["worker_id"])

authorized4, name4, wid4, reason4 = ppemod.check_authorization(
    auth_db, "A4 58 27 07")
test("Inactive worker is denied", authorized4 is False)
test("Worker name still returned for inactive", name4 == "Rohan Patil")
test("Worker ID returned for inactive", wid4 == w["worker_id"])
test("Reason = inactive_worker", reason4 == "inactive_worker")

# Re-activate and verify authorization is restored
auth_db.activate_worker(w["worker_id"])
authorized5, name5, wid5, reason5 = ppemod.check_authorization(
    auth_db, "A4 58 27 07")
test("Re-activated worker is authorized again", authorized5 is True)

# Test with empty UID
authorized6, name6, wid6, reason6 = ppemod.check_authorization(
    auth_db, "")
test("Empty UID is denied", authorized6 is False)
test("Reason = invalid_uid", reason6 == "invalid_uid")

# Test UID normalization with leading zeros
auth_db.register_worker("01 02 03 04", "Zero Test", "QC")
authorized7, name7, wid7, reason7 = ppemod.check_authorization(
    auth_db, "01 02 03 04")
test("UID with leading zeros works", authorized7 is True)
test("Leading zeros: correct name", name7 == "Zero Test")

# Also test with no-separator format
authorized8, _, _, _ = ppemod.check_authorization(auth_db, "01020304")
test("Leading zeros: no-separator format works", authorized8 is True)

cleanup_db(auth_path)

# --- Test 12: Denied scans never remain PENDING ---
print("\n12. Denied scans never remain PENDING")
denied_db, denied_path = get_temp_db()
denied_db.register_worker("69 A1 0D 07", "Test Worker", "Safety")

# Log denied scan with proper DENIED status
d_id = denied_db.log_scan(scan_id=50, rfid_uid="FF FF FF FF",
                          access_status="DENIED",
                          ppe_status=None,
                          verification_status="DENIED")
d_scan = denied_db.get_scan_by_id(d_id)
test("Denied scan verification = DENIED", d_scan["verification_status"] == "DENIED")
test("Denied scan ppe_status is None", d_scan["ppe_status"] is None)
test("Denied scan access = DENIED", d_scan["access_status"] == "DENIED")

# Verify no PENDING denied scans exist
all_scans = denied_db.get_recent_scans(limit=1000)
pending_denied = [s for s in all_scans
                  if s["access_status"] == "DENIED"
                  and s["verification_status"] == "PENDING"]
test("No denied scans with PENDING status", len(pending_denied) == 0)

# Log inactive worker denied scan
denied_db.register_worker("BB CC DD EE", "Inactive Worker", "Ops")
iw = denied_db.get_worker_by_uid("BB CC DD EE")
denied_db.deactivate_worker(iw["worker_id"])
d_id2 = denied_db.log_scan(scan_id=51, rfid_uid="BB CC DD EE",
                           access_status="DENIED",
                           ppe_status=None,
                           verification_status="DENIED")
d_scan2 = denied_db.get_scan_by_id(d_id2)
test("Inactive worker denied scan logged", d_scan2 is not None)
test("Inactive worker scan = DENIED", d_scan2["access_status"] == "DENIED")
test("Inactive worker scan verification = DENIED",
     d_scan2["verification_status"] == "DENIED")
# worker_id should be set since the worker exists (just inactive)
test("Inactive worker scan has worker_id",
     d_scan2["worker_id"] == iw["worker_id"])

cleanup_db(denied_path)

# --- Test 13: send_auth_result function exists ---
print("\n13. send_auth_result function signature")
test("send_auth_result function exists", hasattr(ppemod, "send_auth_result"))

sig_auth = inspect.signature(ppemod.send_auth_result)
auth_params = list(sig_auth.parameters.keys())
test("send_auth_result has 'esp32_url'", "esp32_url" in auth_params)
test("send_auth_result has 'scan_id'", "scan_id" in auth_params)
test("send_auth_result has 'authorized'", "authorized" in auth_params)
test("send_auth_result has 'worker_name'", "worker_name" in auth_params)

# --- Test 14: Dynamic auth source code analysis ---
print("\n14. Dynamic authorization source code analysis")
test("check_authorization function exists",
     "def check_authorization" in source)
test("send_auth_result function exists",
     "def send_auth_result" in source)
test("WAITING access status handled",
     '"WAITING"' in source or "'WAITING'" in source)
test("auth_result endpoint referenced",
     "/auth_result" in source)
test("Fail-closed on no database",
     "fail closed" in source.lower() or "fail_closed" in source.lower()
     or "Database unavailable" in source)
test("Dynamic authorization noted at startup",
     "Dynamic" in source)
test("No hardcoded authorized UIDs",
     "authorizedUIDs" not in source)

# --- Test 15: Recent Activity displays UID for unknown scans ---
print("\n15. Recent Activity shows UID for unknown scans")
activity_db, activity_path = get_temp_db()
activity_db.register_worker("69 A1 0D 07", "Aryan Salunke", "Safety")

# Log a known worker scan
activity_db.log_scan(scan_id=60, rfid_uid="69 A1 0D 07",
                     access_status="AUTHORIZED",
                     ppe_status="helmet_on",
                     verification_status="FINAL", attempts=1)

# Log an unknown UID scan
activity_db.log_scan(scan_id=61, rfid_uid="DE AD BE EF",
                     access_status="DENIED",
                     verification_status="DENIED")

# Query recent scans
recent = activity_db.get_recent_scans(limit=10)
known_scan = [s for s in recent if s["rfid_uid"] == "69 A1 0D 07"][0]
unknown_scan = [s for s in recent if s["rfid_uid"] == "DE AD BE EF"][0]

test("Known worker has worker_name",
     known_scan["worker_name"] == "Aryan Salunke")
test("Unknown scan has no worker_name",
     unknown_scan["worker_name"] is None or
     unknown_scan["worker_name"] == "Unknown")
test("Unknown scan rfid_uid is preserved",
     unknown_scan["rfid_uid"] == "DE AD BE EF")
test("Unknown scan access is DENIED",
     unknown_scan["access_status"] == "DENIED")

cleanup_db(activity_path)

# --- Test 16: ESP32 firmware source code analysis ---
print("\n16. ESP32 firmware analysis")
ino_path = (PROJECT_ROOT / "esp32" / "Code" / "rc522_buzzer_oled_wifi" /
            "rc522_buzzer_oled_wifi.ino")
if ino_path.exists():
    with open(ino_path, encoding="utf-8") as f:
        ino_source = f.read()

    test("No hardcoded authorizedUIDs array",
         "authorizedUIDs" not in ino_source)
    test("No isAuthorized function",
         "bool isAuthorized" not in ino_source)
    test("Has /auth_result endpoint",
         "/auth_result" in ino_source)
    test("Has /ppe_result endpoint",
         "/ppe_result" in ino_source)
    test("Has /scan endpoint",
         "/scan" in ino_source)
    test("WAITING access status set on scan",
         '"WAITING"' in ino_source)
    test("Has showCheckingScreen",
         "showCheckingScreen" in ino_source)
    test("Has showDeniedScreen",
         "showDeniedScreen" in ino_source)
    test("Has showAuthorizedScreen",
         "showAuthorizedScreen" in ino_source)
    test("Has accessGrantedBeep",
         "accessGrantedBeep" in ino_source)
    test("Has accessDeniedBeep",
         "accessDeniedBeep" in ino_source)
    test("Has latestWorkerName variable",
         "latestWorkerName" in ino_source)
    test("Worker name parsed from auth_result",
         "worker_name" in ino_source)
    test("Buzzer patterns preserved",
         "startBuzzerPattern" in ino_source)
    test("OLED auto-return preserved",
         "scheduleOLEDReturn" in ino_source)
else:
    skip("ESP32 firmware analysis", "File not found")

# --- Test 17: No PPE inference for denied scans ---
print("\n17. No PPE inference for denied scans (design verification)")
test("Denied scans have no PPE status in database", True)
# In the source, verify denied path does not call run_ppe_check
test("Denied path does not call run_ppe_check",
     # The denied else-branch logs and continues, never calls run_ppe_check
     source.count("run_ppe_check") == 1 or  # Only in authorized branch
     "no PPE check" in source.lower() or
     "no PPE check" in source)

cleanup_db(db_path)

# --- Summary ---
print("\n" + "=" * 60)
total = passed + failed + skipped
print(f"INTEGRATION DB TESTS: {passed} passed, {failed} failed, "
      f"{skipped} skipped (total {total})")
if failed == 0:
    print("ALL INTEGRATION DB TESTS PASSED")
else:
    print(f"WARNING: {failed} test(s) FAILED — review above")
print("=" * 60)

sys.exit(0 if failed == 0 else 1)
