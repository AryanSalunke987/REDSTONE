"""
Optional Demo Data Seed Script
================================
Populates the SQLite database with sample records for dashboard
demonstration purposes. Does NOT modify the real database unless
explicitly run.

Usage (from project root):
  python database/seed_demo_data.py

This creates demo workers and scan records so you can preview
the dashboard without running the full hardware integration.

WARNING: Only run this for demonstration. The data is fictional.
"""

import sys
import random
from pathlib import Path
from datetime import datetime, timedelta, timezone

# Ensure project root on path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from database.db_manager import PPEDatabase

DB_PATH = PROJECT_ROOT / "database" / "ppe_monitor.db"

# ── Sample data ──
WORKERS = [
    ("69 A1 0D 07", "Aryan Salunke", "Safety"),
    ("A4 58 27 07", "Rohan Patil", "Operations"),
    ("B3 22 1F 0A", "Sneha Desai", "Maintenance"),
    ("C1 44 33 0B", "Vikram Joshi", "Quality Control"),
]

PPE_STATUSES = ["helmet_on", "helmet_on", "helmet_on",
                "helmet_off", "no_person"]  # Weighted toward compliant

def main():
    print("=" * 50)
    print("PPE Monitor — Demo Data Seed Script")
    print("=" * 50)

    db = PPEDatabase(db_path=DB_PATH)
    if not db.initialize_database():
        print("[ERROR] Database initialization failed")
        sys.exit(1)

    # Register workers
    for uid, name, dept in WORKERS:
        result = db.register_worker(uid, name, dept)
        if result["success"]:
            print(f"  Registered: {name} (UID: {uid})")
        else:
            print(f"  Skipped: {name} — {result['message']}")

    # Generate scan records over the last 14 days
    local_tz = datetime.now(timezone.utc).astimezone().tzinfo
    now = datetime.now(local_tz)
    scan_id = 1

    print(f"\nGenerating scan records for the last 14 days...")

    for day_offset in range(14, -1, -1):
        day = now - timedelta(days=day_offset)
        # 3-8 scans per day
        num_scans = random.randint(3, 8)

        for _ in range(num_scans):
            # Pick a random worker or unknown card
            if random.random() < 0.15:
                # Denied scan (unknown card)
                uid = "FF AA BB CC"
                access = "DENIED"
                ppe = None
                v_status = "DENIED"
                attempts = 0
            else:
                uid, name, dept = random.choice(WORKERS)
                access = "AUTHORIZED"
                ppe = random.choice(PPE_STATUSES)
                if ppe == "no_person":
                    v_status = "FINAL"
                    attempts = 3
                elif ppe == "verification_error":
                    v_status = "FAILED"
                    attempts = 1
                else:
                    v_status = "FINAL"
                    attempts = 1

            row_id = db.log_scan(
                scan_id=scan_id, rfid_uid=uid,
                access_status=access,
                ppe_status=ppe,
                verification_status=v_status,
                attempts=attempts
            )

            if row_id:
                # Update verification status if needed
                if access == "AUTHORIZED" and ppe:
                    db.update_scan_result(row_id, ppe, v_status, attempts)

            scan_id += 1

    total_scans = len(db.get_recent_scans(limit=1000))
    summary = db.get_compliance_summary()

    print(f"\n  Total scans created: {total_scans}")
    print(f"  Compliance: {summary['compliance_percentage']}%")
    print(f"  Helmet On: {summary['helmet_on_count']}")
    print(f"  Helmet Off: {summary['helmet_off_count']}")
    print(f"  Denied: {summary['denied_scans']}")
    print(f"\n  Database: {DB_PATH}")
    print("=" * 50)
    print("Demo data ready. Launch dashboard with:")
    print("  streamlit run dashboard/app.py")
    print("=" * 50)


if __name__ == "__main__":
    main()
