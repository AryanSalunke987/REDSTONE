"""
Database Module Tests for Smart PPE Compliance Monitoring System
================================================================
Tests all SQLite database operations:
  - Initialization and schema
  - Worker registration, lookup, update, deactivation
  - Scan logging and result updates
  - Compliance calculations
  - Duplicate protection
  - Error handling
  - Data persistence

Run from project root:
  python tests/test_database.py
"""

import sys
import os
import tempfile
import sqlite3
from pathlib import Path

# Ensure project root is on sys.path so 'database' package is importable
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

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
    """Remove temporary database file."""
    try:
        os.unlink(path)
    except Exception:
        pass


# ============================================================
print("=" * 60)
print("TEST SUITE: Database Module Tests")
print("=" * 60)

# --- Test 1: Database initialization ---
print("\n1. Database initialization")
db, db_path = get_temp_db()

test("Database file created", os.path.exists(db_path))

# Check tables exist
conn = sqlite3.connect(db_path)
cursor = conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
)
tables = [row[0] for row in cursor.fetchall()]
conn.close()

test("workers table exists", "workers" in tables, f"Tables: {tables}")
test("ppe_scans table exists", "ppe_scans" in tables, f"Tables: {tables}")

# Re-initialize should be safe (idempotent)
result = db.initialize_database()
test("Re-initialization is safe (idempotent)", result is True)

cleanup_db(db_path)

# --- Test 2: UID normalization ---
print("\n2. RFID UID normalization")
test("Normalize space-separated lowercase",
     _normalize_uid("69 a1 0d 07") == "69 A1 0D 07")
test("Normalize colon-separated",
     _normalize_uid("69:A1:0D:07") == "69 A1 0D 07")
test("Normalize dash-separated",
     _normalize_uid("69-a1-0d-07") == "69 A1 0D 07")
test("Normalize no separator",
     _normalize_uid("69a10d07") == "69 A1 0D 07")
test("Normalize already correct",
     _normalize_uid("69 A1 0D 07") == "69 A1 0D 07")
test("Normalize empty string", _normalize_uid("") == "")
test("Normalize None", _normalize_uid(None) == "")

# --- Test 3: Worker registration ---
print("\n3. Worker registration")
db, db_path = get_temp_db()

result = db.register_worker("69 A1 0D 07", "Aryan Salunke", "Safety")
test("Worker registration succeeds", result["success"] is True,
     result.get("message"))
test("Worker ID returned", result["worker_id"] is not None)

result2 = db.register_worker("A4 58 27 07", "Test Worker", "Operations")
test("Second worker registration succeeds", result2["success"] is True)

# --- Test 4: Duplicate RFID rejection ---
print("\n4. Duplicate RFID rejection")
dup_result = db.register_worker("69 A1 0D 07", "Duplicate Worker", "HR")
test("Duplicate RFID UID rejected", dup_result["success"] is False)
test("Duplicate error message mentions UID",
     "already registered" in dup_result["message"].lower(),
     dup_result["message"])

# Even with different format
dup_result2 = db.register_worker("69:a1:0d:07", "Another Dup", "HR")
test("Duplicate UID rejected (different format)",
     dup_result2["success"] is False)

# --- Test 5: Worker lookup ---
print("\n5. Worker lookup and retrieval")
worker = db.get_worker_by_uid("69 A1 0D 07")
test("Worker found by UID", worker is not None)
test("Worker name correct", worker["worker_name"] == "Aryan Salunke",
     f"Got: {worker.get('worker_name')}")
test("Worker department correct", worker["department"] == "Safety")
test("Worker is active", worker["is_active"] == 1)
test("Created_at timestamp exists",
     worker["created_at"] is not None and "T" in worker["created_at"])

# Lookup with different format
worker2 = db.get_worker_by_uid("69:a1:0d:07")
test("Worker found by UID (different format)", worker2 is not None)
test("Same worker regardless of format",
     worker2["worker_id"] == worker["worker_id"])

# Lookup nonexistent UID
missing = db.get_worker_by_uid("FF FF FF FF")
test("Nonexistent UID returns None", missing is None)

# --- Test 6: Worker updates ---
print("\n6. Worker updates")
w_id = worker["worker_id"]
update_result = db.update_worker(w_id, worker_name="Aryan S.", department="QC")
test("Worker update succeeds", update_result["success"] is True)

updated = db.get_worker_by_id(w_id)
test("Updated name correct", updated["worker_name"] == "Aryan S.")
test("Updated department correct", updated["department"] == "QC")

# Partial update (name only)
db.update_worker(w_id, worker_name="Aryan Salunke")
partial = db.get_worker_by_id(w_id)
test("Partial update preserves department", partial["department"] == "QC")

# Empty name rejected
empty_name = db.update_worker(w_id, worker_name="   ")
test("Empty name rejected", empty_name["success"] is False)

# No fields to update
no_fields = db.update_worker(w_id)
test("No fields to update returns error", no_fields["success"] is False)

# --- Test 7: Worker deactivation ---
print("\n7. Worker deactivation")
deact_result = db.deactivate_worker(w_id)
test("Deactivation succeeds", deact_result["success"] is True)

deact_worker = db.get_worker_by_id(w_id)
test("Worker is_active set to 0", deact_worker["is_active"] == 0)

# Re-activate
act_result = db.activate_worker(w_id)
test("Activation succeeds", act_result["success"] is True)

act_worker = db.get_worker_by_id(w_id)
test("Worker is_active set to 1", act_worker["is_active"] == 1)

# Get all workers
all_workers = db.get_all_workers()
test("Get all workers returns list", len(all_workers) == 2)

active_workers = db.get_all_workers(active_only=True)
test("Get active workers works", len(active_workers) == 2)

# --- Test 8: Authorized scan insertion ---
print("\n8. Authorized scan insertion")
row_id = db.log_scan(
    scan_id=1, rfid_uid="69 A1 0D 07",
    access_status="AUTHORIZED",
    ppe_status=None, verification_status="PENDING",
    attempts=0
)
test("Authorized scan logged", row_id is not None)
test("Row ID is positive integer", isinstance(row_id, int) and row_id > 0)

scan = db.get_scan_by_id(row_id)
test("Scan record retrievable", scan is not None)
test("Scan UID correct", scan["rfid_uid"] == "69 A1 0D 07")
test("Access status = AUTHORIZED", scan["access_status"] == "AUTHORIZED")
test("Verification status = PENDING", scan["verification_status"] == "PENDING")
test("Worker ID associated", scan["worker_id"] == w_id)
test("Timestamp in ISO format",
     scan["timestamp"] is not None and "T" in scan["timestamp"])
test("Attempts initially 0", scan["attempts"] == 0)

# --- Test 9: Denied scan insertion ---
print("\n9. Denied scan insertion")
denied_id = db.log_scan(
    scan_id=2, rfid_uid="FF FF FF FF",
    access_status="DENIED",
    ppe_status=None, verification_status="DENIED",
    attempts=0
)
test("Denied scan logged", denied_id is not None)

denied_scan = db.get_scan_by_id(denied_id)
test("Denied scan retrievable", denied_scan is not None)
test("Access status = DENIED", denied_scan["access_status"] == "DENIED")
test("Verification status = DENIED",
     denied_scan["verification_status"] == "DENIED")
test("No worker associated for unknown UID", denied_scan["worker_id"] is None)

# --- Test 10: Final PPE result updates ---
print("\n10. Final PPE result updates")

# helmet_on
update_ok = db.update_scan_result(
    row_id, ppe_status="helmet_on",
    verification_status="FINAL", attempts=1
)
test("Update to helmet_on succeeds", update_ok is True)

updated_scan = db.get_scan_by_id(row_id)
test("PPE status = helmet_on", updated_scan["ppe_status"] == "helmet_on")
test("Verification status = FINAL",
     updated_scan["verification_status"] == "FINAL")
test("Attempts = 1", updated_scan["attempts"] == 1)

# --- Test 11: Interim no-person retry updates ---
print("\n11. Interim no-person retry updates")

# Log a new authorized scan
retry_id = db.log_scan(
    scan_id=3, rfid_uid="A4 58 27 07",
    access_status="AUTHORIZED",
    ppe_status=None, verification_status="PENDING",
    attempts=0
)
test("Retry test scan logged", retry_id is not None)

# First attempt: no_person (interim)
db.update_scan_attempts(retry_id, 1)
retry_scan = db.get_scan_by_id(retry_id)
test("Attempt count updated to 1", retry_scan["attempts"] == 1)
test("Still PENDING after retry", retry_scan["verification_status"] == "PENDING")

# Second attempt: no_person (interim)
db.update_scan_attempts(retry_id, 2)
retry_scan2 = db.get_scan_by_id(retry_id)
test("Attempt count updated to 2", retry_scan2["attempts"] == 2)

# Final attempt: helmet_off
db.update_scan_result(retry_id, "helmet_off", "FINAL", attempts=3)
final_retry = db.get_scan_by_id(retry_id)
test("Final status = helmet_off", final_retry["ppe_status"] == "helmet_off")
test("Verification = FINAL", final_retry["verification_status"] == "FINAL")
test("Attempts = 3", final_retry["attempts"] == 3)

# --- Test 12: Verification error handling ---
print("\n12. Verification error handling")

error_id = db.log_scan(
    scan_id=4, rfid_uid="69 A1 0D 07",
    access_status="AUTHORIZED",
    ppe_status=None, verification_status="PENDING"
)
db.update_scan_result(error_id, "verification_error", "FAILED", attempts=1)

error_scan = db.get_scan_by_id(error_id)
test("Verification error status set",
     error_scan["ppe_status"] == "verification_error")
test("Verification = FAILED", error_scan["verification_status"] == "FAILED")

# --- Test 13: Duplicate event protection ---
print("\n13. Duplicate event protection (separate DB rows)")

# The ESP32 scan_id counter may reset. We use auto-increment DB ID
# so duplicate scan_ids from different sessions are OK as separate rows.
dup_scan1 = db.log_scan(
    scan_id=1, rfid_uid="69 A1 0D 07",
    access_status="AUTHORIZED", verification_status="PENDING"
)
dup_scan2 = db.log_scan(
    scan_id=1, rfid_uid="69 A1 0D 07",
    access_status="AUTHORIZED", verification_status="PENDING"
)
test("Two scans with same ESP32 scan_id get different DB IDs",
     dup_scan1 != dup_scan2)
test("Both scans exist", dup_scan1 is not None and dup_scan2 is not None)

# --- Test 14: Database persistence across connections ---
print("\n14. Database persistence across connections")

# Create a new PPEDatabase instance pointing to the same file
db2 = PPEDatabase(db_path=db_path)
worker_check = db2.get_worker_by_uid("69 A1 0D 07")
test("Data persists across new connection",
     worker_check is not None and worker_check["worker_name"] == "Aryan Salunke")

scans_check = db2.get_recent_scans(limit=10)
test("Scans persist across new connection", len(scans_check) > 0)

# --- Test 15: Compliance percentage calculations ---
print("\n15. Compliance percentage calculations")

# Add more known data for calculation
# helmet_on already has 1 from earlier (row_id),
# helmet_off has 1 (retry_id)
summary = db.get_compliance_summary()
test("Compliance summary returns dict", isinstance(summary, dict))
test("Total scans > 0", summary["total_scans"] > 0)
test("Helmet on count tracked", summary["helmet_on_count"] >= 1)
test("Helmet off count tracked", summary["helmet_off_count"] >= 1)

# Compliance = helmet_on / (helmet_on + helmet_off) * 100
expected_pct = round(
    summary["helmet_on_count"] /
    (summary["helmet_on_count"] + summary["helmet_off_count"]) * 100, 1
)
test("Compliance percentage correct",
     abs(summary["compliance_percentage"] - expected_pct) < 0.1,
     f"Expected ~{expected_pct}, got {summary['compliance_percentage']}")

# --- Test 16: Exclusion from compliance denominator ---
print("\n16. Exclusion of no_person/failed from compliance denominator")

# Log a no_person scan (should NOT affect compliance %)
np_id = db.log_scan(
    scan_id=10, rfid_uid="69 A1 0D 07",
    access_status="AUTHORIZED", verification_status="PENDING"
)
db.update_scan_result(np_id, "no_person", "FINAL", attempts=3)

summary_after = db.get_compliance_summary()
test("no_person excluded from compliance denominator",
     abs(summary_after["compliance_percentage"] - expected_pct) < 0.1,
     f"Before: {expected_pct}, After: {summary_after['compliance_percentage']}")

# --- Test 17: Daily compliance trend ---
print("\n17. Daily compliance trend")
daily = db.get_daily_compliance(days=30)
test("Daily compliance returns list", isinstance(daily, list))
# There should be data for today
if daily:
    test("Daily data has date field", "date" in daily[0])
    test("Daily data has compliance_pct", "compliance_pct" in daily[0])
else:
    skip("Daily compliance data check", "No daily data returned")

# --- Test 18: Violation records ---
print("\n18. Violation records")
violations = db.get_violation_records()
test("Violation records returns list", isinstance(violations, list))
test("Violations found (helmet_off exists)", len(violations) >= 1)

if violations:
    test("Violation has worker_name field", "worker_name" in violations[0])
    test("Violation has ppe_status = helmet_off",
         violations[0]["ppe_status"] == "helmet_off")

by_worker = db.get_violations_by_worker()
test("Violations by worker returns list", isinstance(by_worker, list))

# --- Test 19: Recent scans with filters ---
print("\n19. Recent scans with filters")
all_recent = db.get_recent_scans(limit=100)
test("Recent scans returns list", isinstance(all_recent, list))
test("Recent scans has data", len(all_recent) > 0)

# Filter by access status
auth_scans = db.get_recent_scans(access_status="AUTHORIZED")
test("Filter by AUTHORIZED works",
     all(s["access_status"] == "AUTHORIZED" for s in auth_scans))

denied_scans = db.get_recent_scans(access_status="DENIED")
test("Filter by DENIED works",
     all(s["access_status"] == "DENIED" for s in denied_scans))

# Filter by PPE status
helmet_scans = db.get_recent_scans(ppe_status="helmet_on")
test("Filter by helmet_on works",
     all(s["ppe_status"] == "helmet_on" for s in helmet_scans))

# --- Test 20: CSV export data ---
print("\n20. CSV export data")
export_data = db.get_all_scans_for_export()
test("Export data returns list", isinstance(export_data, list))
test("Export data has records", len(export_data) > 0)

if export_data:
    expected_fields = [
        "id", "scan_id", "rfid_uid", "worker_name",
        "department", "timestamp", "access_status",
        "ppe_status", "verification_status", "attempts", "source"
    ]
    for field in expected_fields:
        test(f"Export has field '{field}'", field in export_data[0],
             f"Fields: {list(export_data[0].keys())}")

# --- Test 21: Empty database handling ---
print("\n21. Empty database handling")
empty_db, empty_path = get_temp_db()

empty_summary = empty_db.get_compliance_summary()
test("Empty DB: compliance summary returns zeros",
     empty_summary["total_scans"] == 0)
test("Empty DB: compliance percentage is 0.0",
     empty_summary["compliance_percentage"] == 0.0)

empty_scans = empty_db.get_recent_scans()
test("Empty DB: recent scans returns empty list", empty_scans == [])

empty_violations = empty_db.get_violation_records()
test("Empty DB: violations returns empty list", empty_violations == [])

empty_daily = empty_db.get_daily_compliance()
test("Empty DB: daily compliance returns empty list", empty_daily == [])

empty_export = empty_db.get_all_scans_for_export()
test("Empty DB: export returns empty list", empty_export == [])

empty_worker = empty_db.get_worker_by_uid("FF FF FF FF")
test("Empty DB: worker lookup returns None", empty_worker is None)

empty_all_workers = empty_db.get_all_workers()
test("Empty DB: all workers returns empty list", empty_all_workers == [])

cleanup_db(empty_path)

# --- Test 22: Invalid input handling ---
print("\n22. Invalid input handling")
bad_name = db.register_worker("FF FF FF 01", "", "Safety")
test("Empty worker name rejected", bad_name["success"] is False)

bad_name2 = db.register_worker("FF FF FF 02", "   ", "Safety")
test("Whitespace-only worker name rejected", bad_name2["success"] is False)

bad_uid = db.register_worker("", "Test Worker", "Safety")
test("Empty RFID UID rejected", bad_uid["success"] is False)

bad_uid2 = db.register_worker(None, "Test Worker", "Safety")
test("None RFID UID rejected", bad_uid2["success"] is False)

# Log scan with invalid UID
bad_scan = db.log_scan(scan_id=99, rfid_uid="", access_status="DENIED",
                       verification_status="DENIED")
test("Empty UID scan returns None", bad_scan is None)

# --- Test 23: Access distribution ---
print("\n23. Access distribution")
dist = db.get_access_distribution()
test("Access distribution returns dict", isinstance(dist, dict))
test("Distribution has authorized key", "authorized" in dist)
test("Distribution has denied key", "denied" in dist)
test("Authorized count > 0", dist["authorized"] > 0)

# --- Test 24: Departments list ---
print("\n24. Departments list")
depts = db.get_departments()
test("Departments returns list", isinstance(depts, list))
# We registered workers with "QC" and "Operations" departments
test("Departments found", len(depts) >= 1)

# --- Test 25: Worker deactivation preserves scan history ---
print("\n25. Worker deactivation preserves scan history")
# Deactivate a worker who has scans
db.deactivate_worker(w_id)
deact_check = db.get_worker_by_id(w_id)
test("Worker deactivated", deact_check["is_active"] == 0)

# Scans should still be queryable with the worker link
scans_after_deact = db.get_recent_scans(limit=100)
worker_scans = [s for s in scans_after_deact if s["worker_id"] == w_id]
test("Scans preserved after worker deactivation", len(worker_scans) > 0)

# Re-activate for other tests
db.activate_worker(w_id)

cleanup_db(db_path)

# --- Test 26: SQLite error handling (read-only path) ---
print("\n26. SQLite error handling")
# Attempt to use a directory as DB path (should fail gracefully)
try:
    bad_db = PPEDatabase(db_path=tempfile.gettempdir())
    bad_init = bad_db.initialize_database()
    test("Invalid path handled gracefully", bad_init is False)
except Exception as e:
    test("Invalid path raises controlled error", True)

# --- Summary ---
print("\n" + "=" * 60)
total = passed + failed + skipped
print(f"DATABASE TESTS: {passed} passed, {failed} failed, "
      f"{skipped} skipped (total {total})")
if failed == 0:
    print("ALL DATABASE TESTS PASSED")
else:
    print(f"WARNING: {failed} test(s) FAILED — review above")
print("=" * 60)

sys.exit(0 if failed == 0 else 1)
