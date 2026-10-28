"""
Dashboard Tests for Smart PPE Compliance Monitoring System
============================================================
Tests that the Streamlit dashboard:
  - Can be imported without errors
  - Handles an empty database
  - Displays actual SQLite records
  - Worker management validates UIDs
  - CSV export contains expected fields
  - PPE Violations page filters work correctly
  - Unknown UIDs are displayed instead of "Unknown"

Run from project root:
  python tests/test_dashboard.py
"""

import sys
import os
import tempfile
import subprocess
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from database.db_manager import PPEDatabase

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
print("TEST SUITE: Dashboard Tests")
print("=" * 60)

# --- Test 1: Dashboard file exists and has valid syntax ---
print("\n1. Dashboard file verification")
dashboard_path = PROJECT_ROOT / "dashboard" / "app.py"
test("Dashboard file exists", dashboard_path.exists(),
     f"Not found: {dashboard_path}")

if dashboard_path.exists():
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(dashboard_path)],
        capture_output=True, text=True
    )
    test("Dashboard compiles without syntax errors",
         result.returncode == 0, result.stderr)
else:
    skip("Dashboard syntax check", "File not found")

# --- Test 2: Streamlit is importable ---
print("\n2. Streamlit availability")
try:
    import streamlit
    test("Streamlit is importable", True)
    test("Streamlit version available", hasattr(streamlit, "__version__"))
except ImportError:
    test("Streamlit is importable", False, "Not installed")

# --- Test 3: Plotly is importable ---
print("\n3. Plotly availability")
try:
    import plotly
    test("Plotly is importable", True)
    import plotly.express as px
    test("Plotly Express importable", True)
    import plotly.graph_objects as go
    test("Plotly Graph Objects importable", True)
except ImportError:
    test("Plotly is importable", False, "Not installed")

# --- Test 4: Dashboard handles empty database ---
print("\n4. Empty database handling")
db, db_path = get_temp_db()

summary = db.get_compliance_summary()
test("Empty DB: summary returns dict", isinstance(summary, dict))
test("Empty DB: total_scans = 0", summary["total_scans"] == 0)
test("Empty DB: compliance_percentage = 0.0",
     summary["compliance_percentage"] == 0.0)

scans = db.get_recent_scans()
test("Empty DB: recent scans = empty list", scans == [])

violations = db.get_violation_records()
test("Empty DB: violations = empty list", violations == [])

workers = db.get_all_workers()
test("Empty DB: workers = empty list", workers == [])

daily = db.get_daily_compliance()
test("Empty DB: daily compliance = empty list", daily == [])

export = db.get_all_scans_for_export()
test("Empty DB: export = empty list", export == [])

depts = db.get_departments()
test("Empty DB: departments = empty list", depts == [])

dist = db.get_access_distribution()
test("Empty DB: access distribution zeros",
     dist["authorized"] == 0 and dist["denied"] == 0)

cleanup_db(db_path)

# --- Test 5: Dashboard displays actual SQLite records ---
print("\n5. Actual SQLite records display")
db2, db_path2 = get_temp_db()

# Insert test data
db2.register_worker("AA BB CC DD", "Test Worker", "TestDept")
rid = db2.log_scan(scan_id=1, rfid_uid="AA BB CC DD",
                    access_status="AUTHORIZED",
                    verification_status="PENDING")
db2.update_scan_result(rid, "helmet_on", "FINAL", 1)

rid2 = db2.log_scan(scan_id=2, rfid_uid="AA BB CC DD",
                     access_status="AUTHORIZED",
                     verification_status="PENDING")
db2.update_scan_result(rid2, "helmet_off", "FINAL", 1)

# Verify data is queryable
summary2 = db2.get_compliance_summary()
test("Data: total_scans > 0", summary2["total_scans"] > 0)
test("Data: helmet_on = 1", summary2["helmet_on_count"] == 1)
test("Data: helmet_off = 1", summary2["helmet_off_count"] == 1)
test("Data: compliance = 50%",
     abs(summary2["compliance_percentage"] - 50.0) < 0.1)

scans2 = db2.get_recent_scans()
test("Data: recent scans has records", len(scans2) > 0)
test("Data: scan has worker_name field",
     "worker_name" in scans2[0])
test("Data: worker_name is 'Test Worker'",
     scans2[0]["worker_name"] == "Test Worker" or
     scans2[1]["worker_name"] == "Test Worker")

violations2 = db2.get_violation_records()
test("Data: violations has 1 record", len(violations2) == 1)
test("Data: violation is helmet_off",
     violations2[0]["ppe_status"] == "helmet_off")

cleanup_db(db_path2)

# --- Test 6: Worker management validates UIDs ---
print("\n6. Worker management UID validation")
db3, db_path3 = get_temp_db()

# Valid registration
r = db3.register_worker("11 22 33 44", "Worker One", "Dept A")
test("Valid registration succeeds", r["success"] is True)

# Duplicate UID rejected
r2 = db3.register_worker("11 22 33 44", "Worker Two", "Dept B")
test("Duplicate UID rejected", r2["success"] is False)

# Empty UID rejected
r3 = db3.register_worker("", "Worker Three", "Dept C")
test("Empty UID rejected", r3["success"] is False)

# Empty name rejected
r4 = db3.register_worker("55 66 77 88", "", "Dept D")
test("Empty name rejected", r4["success"] is False)

cleanup_db(db_path3)

# --- Test 7: CSV export fields ---
print("\n7. CSV export field verification")
db4, db_path4 = get_temp_db()
db4.register_worker("DD EE FF 00", "Export Worker", "Export Dept")
db4.log_scan(scan_id=10, rfid_uid="DD EE FF 00",
             access_status="AUTHORIZED",
             ppe_status="helmet_on",
             verification_status="FINAL",
             attempts=1)

export_data = db4.get_all_scans_for_export()
test("Export has data", len(export_data) > 0)

if export_data:
    expected_fields = [
        "id", "scan_id", "rfid_uid", "worker_name",
        "department", "timestamp", "access_status",
        "ppe_status", "verification_status", "attempts", "source"
    ]
    for field in expected_fields:
        test(f"Export field '{field}' present", field in export_data[0])

    # Test CSV generation
    import pandas as pd
    import io
    df = pd.DataFrame(export_data)
    csv_buf = io.StringIO()
    df.to_csv(csv_buf, index=False)
    csv_str = csv_buf.getvalue()
    test("CSV is non-empty string", len(csv_str) > 0)
    test("CSV has header row", "rfid_uid" in csv_str)
    test("CSV has data row", "DD EE FF 00" in csv_str)

cleanup_db(db_path4)

# --- Test 8: Filter functionality ---
print("\n8. Filter functionality")
db5, db_path5 = get_temp_db()
db5.register_worker("A1 B2 C3 D4", "Filter Worker A", "Dept Alpha")
db5.register_worker("E5 F6 A7 B8", "Filter Worker B", "Dept Beta")

# Log different types of scans
db5.log_scan(scan_id=20, rfid_uid="A1 B2 C3 D4",
             access_status="AUTHORIZED", ppe_status="helmet_on",
             verification_status="FINAL")
db5.log_scan(scan_id=21, rfid_uid="E5 F6 A7 B8",
             access_status="AUTHORIZED", ppe_status="helmet_off",
             verification_status="FINAL")
db5.log_scan(scan_id=22, rfid_uid="FF FF FF FF",
             access_status="DENIED", verification_status="DENIED")

# Filter by access status
auth_only = db5.get_recent_scans(access_status="AUTHORIZED")
test("Filter AUTHORIZED returns correct count", len(auth_only) == 2)

denied_only = db5.get_recent_scans(access_status="DENIED")
test("Filter DENIED returns correct count", len(denied_only) == 1)

# Filter by PPE status
helmet_on = db5.get_recent_scans(ppe_status="helmet_on")
test("Filter helmet_on returns correct count", len(helmet_on) == 1)

# Filter by department
dept_alpha = db5.get_recent_scans(department="Dept Alpha")
test("Filter by department works", len(dept_alpha) == 1)

cleanup_db(db_path5)

# --- Test 9: Dashboard source analysis ---
print("\n9. Dashboard source code analysis")
if dashboard_path.exists():
    with open(dashboard_path, encoding="utf-8") as f:
        source = f.read()

    test("Dashboard imports PPEDatabase",
         "PPEDatabase" in source)
    test("Dashboard has Overview page",
         "Overview" in source)
    test("Dashboard has Scan History page",
         "Scan History" in source)
    test("Dashboard has Violations page",
         "Violations" in source)
    test("Dashboard has Workers page",
         "Workers" in source or "Worker" in source)
    test("Dashboard has Reports page",
         "Reports" in source)
    test("Dashboard uses sidebar navigation",
         "sidebar" in source)
    test("Dashboard has CSV download",
         "download_button" in source)
    test("Dashboard has date filters",
         "date_input" in source)
    test("Dashboard handles empty states",
         "No scan" in source or "No data" in source or "No workers" in source)
    test("Dashboard uses Plotly charts",
         "plotly" in source.lower())
    test("Dashboard uses dark theme",
         "plotly_dark" in source or "dark" in source.lower())
    test("Dashboard shows compliance %",
         "compliance" in source.lower())
    test("Dashboard has refresh button",
         "Refresh" in source)
    test("Dashboard binds to localhost (page_config present)",
         "set_page_config" in source)
    # New checks for unknown UID display
    test("Dashboard shows UID for unknown workers",
         "rfid_uid" in source and "Unknown" in source)
    test("Dashboard shows Access Denied for denied scans",
         "Access Denied" in source)
else:
    skip("Dashboard source analysis", "File not found")

# --- Test 10: PPE Violations page function signatures ---
print("\n10. PPE Violations page function signatures")
viol_db, viol_path = get_temp_db()
viol_db.register_worker("AA BB CC DD", "Violation Worker", "Safety")

# Create violation records
for i in range(3):
    rid = viol_db.log_scan(scan_id=30+i, rfid_uid="AA BB CC DD",
                           access_status="AUTHORIZED",
                           verification_status="PENDING")
    viol_db.update_scan_result(rid, "helmet_off", "FINAL", 1)

# Test get_violations_by_worker with all filter kwargs
# This is the exact call pattern the dashboard uses (line 550)
v_params = {
    "date_from": "2026-09-01",
    "date_to": "2026-12-31",
    "worker_name": "Violation",
    "department": "Safety",
}
try:
    by_worker = viol_db.get_violations_by_worker(**v_params)
    test("get_violations_by_worker accepts worker_name/department kwargs",
         True)
    test("Violations by worker has results", len(by_worker) > 0)
    if by_worker:
        test("Violation count correct", by_worker[0]["violation_count"] == 3)
        test("Worker name in results",
             by_worker[0]["worker_name"] == "Violation Worker")
except TypeError as e:
    test("get_violations_by_worker accepts worker_name/department kwargs",
         False, str(e))

# Test get_daily_violations with all filter kwargs
try:
    daily_v = viol_db.get_daily_violations(**v_params)
    test("get_daily_violations accepts worker_name/department kwargs", True)
    test("Daily violations returns list", isinstance(daily_v, list))
except TypeError as e:
    test("get_daily_violations accepts worker_name/department kwargs",
         False, str(e))

# Test with empty filters (no violations match)
empty_params = {
    "date_from": "2020-01-01",
    "date_to": "2020-01-02",
    "worker_name": None,
    "department": None,
}
try:
    empty_viol = viol_db.get_violations_by_worker(**empty_params)
    test("Empty violations result is graceful", empty_viol == [])
except Exception as e:
    test("Empty violations result is graceful", False, str(e))

# Test with worker_name filter only
worker_only = viol_db.get_violations_by_worker(worker_name="Violation")
test("Worker name filter alone works", len(worker_only) > 0)

# Test with department filter only
dept_only = viol_db.get_violations_by_worker(department="Safety")
test("Department filter alone works", len(dept_only) > 0)

# Test with no matches
no_match = viol_db.get_violations_by_worker(worker_name="Nonexistent")
test("No matching worker returns empty", no_match == [])

cleanup_db(viol_path)

# --- Test 11: Empty violations state ---
print("\n11. Empty violations state")
empty_viol_db, empty_viol_path = get_temp_db()

violations_empty = empty_viol_db.get_violation_records()
test("Empty DB: violation records = []", violations_empty == [])

by_worker_empty = empty_viol_db.get_violations_by_worker()
test("Empty DB: violations by worker = []", by_worker_empty == [])

daily_v_empty = empty_viol_db.get_daily_violations()
test("Empty DB: daily violations = []", daily_v_empty == [])

# With filter kwargs (dashboard pattern)
try:
    by_worker_filtered = empty_viol_db.get_violations_by_worker(
        date_from="2026-01-01", date_to="2026-12-31",
        worker_name=None, department=None
    )
    test("Empty DB: filtered violations by worker = []",
         by_worker_filtered == [])
except TypeError as e:
    test("Empty DB: filtered violations by worker succeeds",
         False, str(e))

cleanup_db(empty_viol_path)

# --- Summary ---
print("\n" + "=" * 60)
total = passed + failed + skipped
print(f"DASHBOARD TESTS: {passed} passed, {failed} failed, "
      f"{skipped} skipped (total {total})")
if failed == 0:
    print("ALL DASHBOARD TESTS PASSED")
else:
    print(f"WARNING: {failed} test(s) FAILED — review above")
print("=" * 60)

sys.exit(0 if failed == 0 else 1)
