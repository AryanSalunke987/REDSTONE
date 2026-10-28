"""
Database Manager for Smart PPE Compliance Monitoring System
============================================================
Provides all SQLite operations for worker registration, scan logging,
compliance queries and dashboard data.

Uses Python's built-in sqlite3 module with parameterized queries.
All timestamps use ISO 8601 format with the system's local timezone offset.

Usage:
    from database.db_manager import PPEDatabase

    db = PPEDatabase()          # Uses default project-relative path
    db.initialize_database()    # Create tables if they don't exist
    db.register_worker("69 A1 0D 07", "Aryan Salunke", "Safety")
    db.log_scan(scan_id=1, rfid_uid="69 A1 0D 07", access_status="AUTHORIZED")
"""

import sqlite3
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta

# ── Logger ──────────────────────────────────────────────────
logger = logging.getLogger("ppe_database")

# ── Default database path (project-relative) ───────────────
# Resolves to: <project_root>/database/ppe_monitor.db
DEFAULT_DB_PATH = Path(__file__).parent / "ppe_monitor.db"

# ── Local timezone helper ───────────────────────────────────
# System local offset (IST = +05:30 on the developer's machine)
_LOCAL_TZ = datetime.now(timezone.utc).astimezone().tzinfo


def _now_iso():
    """Return the current local time as an ISO 8601 string with timezone."""
    return datetime.now(_LOCAL_TZ).isoformat()


def _normalize_uid(uid):
    """
    Normalize an RFID UID to uppercase, space-separated hex format.
    Accepts various separators: spaces, colons, dashes, or no separator.
    Example inputs:  '69 a1 0d 07', '69:A1:0D:07', '69a10d07'
    Output:          '69 A1 0D 07'
    """
    if not uid or not isinstance(uid, str):
        return ""
    # Remove common separators and whitespace
    cleaned = uid.upper().replace(":", "").replace("-", "").replace(" ", "")
    # Group into byte pairs
    pairs = [cleaned[i:i+2] for i in range(0, len(cleaned), 2)]
    return " ".join(pairs)


class PPEDatabase:
    """
    Thread-aware SQLite database manager for the PPE monitoring system.

    Each method opens and closes its own connection using a context manager
    to avoid keeping connections open indefinitely. This is safe for the
    single-writer, few-reader pattern of this application.
    """

    def __init__(self, db_path=None):
        """
        Initialize with a database file path.

        Args:
            db_path: Path to the SQLite database file.
                     Defaults to <project_root>/database/ppe_monitor.db
        """
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        logger.info(f"Database path: {self.db_path}")

    def get_database_connection(self):
        """
        Create and return a new SQLite connection with recommended settings.
        Caller is responsible for closing the connection.

        Returns:
            sqlite3.Connection with row_factory set to sqlite3.Row
        """
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")     # Better concurrency
        conn.execute("PRAGMA foreign_keys=ON")       # Enforce FK constraints
        return conn

    def _execute(self, sql, params=None, fetch=False, fetchone=False,
                 commit=True):
        """
        Internal helper: execute a SQL statement with proper lifecycle.

        Args:
            sql:      SQL query string with ? placeholders
            params:   Tuple of parameter values
            fetch:    If True, return all rows as list of dicts
            fetchone: If True, return a single row as dict (or None)
            commit:   If True, commit after execution

        Returns:
            List[dict] | dict | int (lastrowid) | None
        """
        conn = None
        try:
            conn = self.get_database_connection()
            cursor = conn.cursor()
            cursor.execute(sql, params or ())

            if fetch:
                rows = cursor.fetchall()
                result = [dict(row) for row in rows]
            elif fetchone:
                row = cursor.fetchone()
                result = dict(row) if row else None
            else:
                result = cursor.lastrowid

            if commit:
                conn.commit()
            return result

        except sqlite3.Error as e:
            logger.error(f"Database error: {e} | SQL: {sql}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()

    # ════════════════════════════════════════════════════════════
    # INITIALIZATION
    # ════════════════════════════════════════════════════════════

    def initialize_database(self):
        """
        Create tables and indexes if they don't already exist.
        Safe to call multiple times — uses CREATE TABLE IF NOT EXISTS.

        Returns:
            True on success, False on failure.
        """
        schema_path = Path(__file__).parent / "schema.sql"
        if not schema_path.exists():
            logger.error(f"Schema file not found: {schema_path}")
            return False

        try:
            conn = self.get_database_connection()
            with open(schema_path, "r") as f:
                schema_sql = f.read()
            conn.executescript(schema_sql)
            conn.commit()
            conn.close()
            logger.info("Database initialized successfully")
            return True
        except sqlite3.Error as e:
            logger.error(f"Database initialization failed: {e}")
            return False

    # ════════════════════════════════════════════════════════════
    # WORKER MANAGEMENT
    # ════════════════════════════════════════════════════════════

    def register_worker(self, rfid_uid, worker_name, department=None):
        """
        Register a new worker with an RFID card UID.

        Args:
            rfid_uid:    RFID card UID string (will be normalized)
            worker_name: Worker's display name
            department:  Optional department or work area

        Returns:
            dict with 'success' (bool), 'worker_id' (int|None),
            'message' (str)
        """
        uid = _normalize_uid(rfid_uid)
        if not uid:
            return {"success": False, "worker_id": None,
                    "message": "Invalid RFID UID"}
        if not worker_name or not worker_name.strip():
            return {"success": False, "worker_id": None,
                    "message": "Worker name is required"}

        try:
            worker_id = self._execute(
                """INSERT INTO workers (rfid_uid, worker_name, department,
                                        is_active, created_at)
                   VALUES (?, ?, ?, 1, ?)""",
                (uid, worker_name.strip(), department, _now_iso())
            )
            logger.info(f"Worker registered: {worker_name} (UID: {uid})")
            return {"success": True, "worker_id": worker_id,
                    "message": f"Worker '{worker_name}' registered successfully"}
        except sqlite3.IntegrityError:
            return {"success": False, "worker_id": None,
                    "message": f"RFID UID '{uid}' is already registered"}
        except sqlite3.Error as e:
            logger.error(f"Worker registration failed: {e}")
            return {"success": False, "worker_id": None,
                    "message": f"Database error: {e}"}

    def update_worker(self, worker_id, worker_name=None, department=None):
        """
        Update an existing worker's name and/or department.

        Args:
            worker_id:   Integer worker ID
            worker_name: New name (or None to keep current)
            department:  New department (or None to keep current)

        Returns:
            dict with 'success' (bool) and 'message' (str)
        """
        # Build dynamic UPDATE
        fields = []
        params = []
        if worker_name is not None:
            if not worker_name.strip():
                return {"success": False,
                        "message": "Worker name cannot be empty"}
            fields.append("worker_name = ?")
            params.append(worker_name.strip())
        if department is not None:
            fields.append("department = ?")
            params.append(department)

        if not fields:
            return {"success": False, "message": "No fields to update"}

        params.append(worker_id)
        sql = f"UPDATE workers SET {', '.join(fields)} WHERE worker_id = ?"

        try:
            self._execute(sql, tuple(params))
            logger.info(f"Worker {worker_id} updated")
            return {"success": True, "message": "Worker updated successfully"}
        except sqlite3.Error as e:
            logger.error(f"Worker update failed: {e}")
            return {"success": False, "message": f"Database error: {e}"}

    def deactivate_worker(self, worker_id):
        """
        Deactivate a worker (soft delete). Historical scans are preserved.

        Args:
            worker_id: Integer worker ID

        Returns:
            dict with 'success' (bool) and 'message' (str)
        """
        try:
            self._execute(
                "UPDATE workers SET is_active = 0 WHERE worker_id = ?",
                (worker_id,)
            )
            logger.info(f"Worker {worker_id} deactivated")
            return {"success": True,
                    "message": "Worker deactivated successfully"}
        except sqlite3.Error as e:
            logger.error(f"Worker deactivation failed: {e}")
            return {"success": False, "message": f"Database error: {e}"}

    def activate_worker(self, worker_id):
        """
        Re-activate a previously deactivated worker.

        Args:
            worker_id: Integer worker ID

        Returns:
            dict with 'success' (bool) and 'message' (str)
        """
        try:
            self._execute(
                "UPDATE workers SET is_active = 1 WHERE worker_id = ?",
                (worker_id,)
            )
            logger.info(f"Worker {worker_id} activated")
            return {"success": True,
                    "message": "Worker activated successfully"}
        except sqlite3.Error as e:
            logger.error(f"Worker activation failed: {e}")
            return {"success": False, "message": f"Database error: {e}"}

    def get_worker_by_uid(self, rfid_uid):
        """
        Look up a worker by RFID UID.

        Args:
            rfid_uid: RFID card UID string (will be normalized)

        Returns:
            dict with worker fields, or None if not found
        """
        uid = _normalize_uid(rfid_uid)
        if not uid:
            return None
        return self._execute(
            "SELECT * FROM workers WHERE rfid_uid = ?",
            (uid,), fetchone=True
        )

    def get_worker_by_id(self, worker_id):
        """
        Look up a worker by their database ID.

        Args:
            worker_id: Integer worker ID

        Returns:
            dict with worker fields, or None if not found
        """
        return self._execute(
            "SELECT * FROM workers WHERE worker_id = ?",
            (worker_id,), fetchone=True
        )

    def get_all_workers(self, active_only=False):
        """
        Retrieve all registered workers.

        Args:
            active_only: If True, only return active workers

        Returns:
            List of worker dicts
        """
        if active_only:
            return self._execute(
                "SELECT * FROM workers WHERE is_active = 1 "
                "ORDER BY worker_name",
                fetch=True
            )
        return self._execute(
            "SELECT * FROM workers ORDER BY worker_name",
            fetch=True
        )

    # ════════════════════════════════════════════════════════════
    # SCAN LOGGING
    # ════════════════════════════════════════════════════════════

    def log_scan(self, scan_id, rfid_uid, access_status,
                 ppe_status=None, verification_status="PENDING",
                 attempts=0, source="ESP32"):
        """
        Insert a new PPE scan record into the database.

        Automatically looks up the worker by RFID UID and associates
        the scan with the worker_id if found (and active).

        Args:
            scan_id:             ESP32 scan counter
            rfid_uid:            Scanned RFID UID
            access_status:       'AUTHORIZED' or 'DENIED'
            ppe_status:          PPE detection result (or None for denied/pending)
            verification_status: 'PENDING', 'FINAL', 'FAILED', or 'DENIED'
            attempts:            Number of AI detection attempts so far
            source:              Scan origin (default 'ESP32')

        Returns:
            int: Database row ID of the inserted scan, or None on failure
        """
        uid = _normalize_uid(rfid_uid)
        if not uid:
            logger.error("Cannot log scan: invalid RFID UID")
            return None

        # Look up worker (only associate if registered)
        worker = self.get_worker_by_uid(uid)
        worker_id = worker["worker_id"] if worker else None

        try:
            row_id = self._execute(
                """INSERT INTO ppe_scans
                   (scan_id, rfid_uid, worker_id, timestamp,
                    access_status, ppe_status, verification_status,
                    attempts, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (scan_id, uid, worker_id, _now_iso(),
                 access_status, ppe_status, verification_status,
                 attempts, source)
            )
            logger.info(
                f"Scan logged: id={row_id}, scan_id={scan_id}, "
                f"uid={uid}, access={access_status}"
            )
            return row_id
        except sqlite3.Error as e:
            logger.error(f"Scan logging failed: {e}")
            return None

    def update_scan_result(self, db_row_id, ppe_status,
                           verification_status, attempts=None):
        """
        Update an existing scan record with the final PPE result.

        Args:
            db_row_id:           Database row ID (from log_scan)
            ppe_status:          Final PPE status string
            verification_status: 'FINAL', 'FAILED', etc.
            attempts:            Updated attempt count (or None to skip)

        Returns:
            True on success, False on failure
        """
        try:
            if attempts is not None:
                self._execute(
                    """UPDATE ppe_scans
                       SET ppe_status = ?, verification_status = ?,
                           attempts = ?
                       WHERE id = ?""",
                    (ppe_status, verification_status, attempts, db_row_id)
                )
            else:
                self._execute(
                    """UPDATE ppe_scans
                       SET ppe_status = ?, verification_status = ?
                       WHERE id = ?""",
                    (ppe_status, verification_status, db_row_id)
                )
            logger.info(
                f"Scan updated: id={db_row_id}, ppe={ppe_status}, "
                f"status={verification_status}"
            )
            return True
        except sqlite3.Error as e:
            logger.error(f"Scan update failed: {e}")
            return False

    def update_scan_attempts(self, db_row_id, attempts):
        """
        Update only the attempt count on a scan record (for retries).

        Args:
            db_row_id: Database row ID
            attempts:  New attempt count

        Returns:
            True on success, False on failure
        """
        try:
            self._execute(
                "UPDATE ppe_scans SET attempts = ? WHERE id = ?",
                (attempts, db_row_id)
            )
            return True
        except sqlite3.Error as e:
            logger.error(f"Attempt update failed: {e}")
            return False

    # ════════════════════════════════════════════════════════════
    # QUERY FUNCTIONS (Dashboard)
    # ════════════════════════════════════════════════════════════

    def get_recent_scans(self, limit=50, offset=0,
                         date_from=None, date_to=None,
                         worker_name=None, department=None,
                         ppe_status=None, access_status=None):
        """
        Retrieve recent scan records with optional filters.
        Joins with workers table to include worker name and department.

        Returns:
            List of scan dicts with worker info
        """
        conditions = []
        params = []

        if date_from:
            conditions.append("s.timestamp >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("s.timestamp <= ?")
            params.append(date_to)
        if worker_name:
            conditions.append("w.worker_name LIKE ?")
            params.append(f"%{worker_name}%")
        if department:
            conditions.append("w.department = ?")
            params.append(department)
        if ppe_status:
            conditions.append("s.ppe_status = ?")
            params.append(ppe_status)
        if access_status:
            conditions.append("s.access_status = ?")
            params.append(access_status)

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        params.extend([limit, offset])

        sql = f"""
            SELECT s.*, w.worker_name, w.department
            FROM ppe_scans s
            LEFT JOIN workers w ON s.worker_id = w.worker_id
            {where_clause}
            ORDER BY s.timestamp DESC
            LIMIT ? OFFSET ?
        """
        return self._execute(sql, tuple(params), fetch=True)

    def get_compliance_summary(self, date_from=None, date_to=None):
        """
        Calculate overall compliance statistics.

        Compliance % = helmet_on / (helmet_on + helmet_off) * 100
        Excludes no_person, verification_error, pending and denied scans.

        Returns:
            dict with all KPI values
        """
        conditions = ["s.verification_status IN ('FINAL', 'FAILED', 'DENIED')"]
        params = []

        if date_from:
            conditions.append("s.timestamp >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("s.timestamp <= ?")
            params.append(date_to)

        where_clause = "WHERE " + " AND ".join(conditions)

        sql = f"""
            SELECT
                COUNT(*) as total_scans,
                SUM(CASE WHEN s.access_status = 'AUTHORIZED' THEN 1 ELSE 0 END)
                    as authorized_scans,
                SUM(CASE WHEN s.access_status = 'DENIED' THEN 1 ELSE 0 END)
                    as denied_scans,
                SUM(CASE WHEN s.ppe_status = 'helmet_on' THEN 1 ELSE 0 END)
                    as helmet_on_count,
                SUM(CASE WHEN s.ppe_status = 'helmet_off' THEN 1 ELSE 0 END)
                    as helmet_off_count,
                SUM(CASE WHEN s.ppe_status = 'no_person' THEN 1 ELSE 0 END)
                    as no_person_count,
                SUM(CASE WHEN s.ppe_status = 'verification_error'
                         OR s.verification_status = 'FAILED' THEN 1 ELSE 0 END)
                    as verification_failures
            FROM ppe_scans s
            {where_clause}
        """

        result = self._execute(sql, tuple(params), fetchone=True)

        if not result:
            return {
                "total_scans": 0, "authorized_scans": 0,
                "denied_scans": 0, "helmet_on_count": 0,
                "helmet_off_count": 0, "no_person_count": 0,
                "verification_failures": 0, "compliance_percentage": 0.0
            }

        helmet_on = result["helmet_on_count"] or 0
        helmet_off = result["helmet_off_count"] or 0
        denominator = helmet_on + helmet_off

        compliance_pct = (helmet_on / denominator * 100) if denominator > 0 else 0.0

        return {
            "total_scans": result["total_scans"] or 0,
            "authorized_scans": result["authorized_scans"] or 0,
            "denied_scans": result["denied_scans"] or 0,
            "helmet_on_count": helmet_on,
            "helmet_off_count": helmet_off,
            "no_person_count": result["no_person_count"] or 0,
            "verification_failures": result["verification_failures"] or 0,
            "compliance_percentage": round(compliance_pct, 1)
        }

    def get_daily_compliance(self, days=30, date_from=None, date_to=None):
        """
        Get daily helmet compliance trend data.

        Returns:
            List of dicts: [{date, helmet_on, helmet_off, total, compliance_pct}]
        """
        conditions = [
            "s.access_status = 'AUTHORIZED'",
            "s.verification_status = 'FINAL'",
            "s.ppe_status IN ('helmet_on', 'helmet_off')"
        ]
        params = []

        if date_from:
            conditions.append("s.timestamp >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("s.timestamp <= ?")
            params.append(date_to)

        if not date_from and not date_to:
            conditions.append(
                f"date(s.timestamp) >= date('now', '-{int(days)} days')"
            )

        where_clause = "WHERE " + " AND ".join(conditions)

        sql = f"""
            SELECT
                date(s.timestamp) as date,
                SUM(CASE WHEN s.ppe_status = 'helmet_on' THEN 1 ELSE 0 END)
                    as helmet_on,
                SUM(CASE WHEN s.ppe_status = 'helmet_off' THEN 1 ELSE 0 END)
                    as helmet_off,
                COUNT(*) as total
            FROM ppe_scans s
            {where_clause}
            GROUP BY date(s.timestamp)
            ORDER BY date(s.timestamp)
        """

        rows = self._execute(sql, tuple(params), fetch=True)

        # Calculate compliance percentage per day
        for row in rows:
            denom = (row["helmet_on"] or 0) + (row["helmet_off"] or 0)
            row["compliance_pct"] = (
                round((row["helmet_on"] or 0) / denom * 100, 1)
                if denom > 0 else 0.0
            )

        return rows

    def get_violation_records(self, limit=100, date_from=None, date_to=None,
                              worker_name=None, department=None):
        """
        Retrieve helmet-off violation records.
        Only includes confirmed helmet_off with FINAL verification.

        Returns:
            List of violation dicts with worker info
        """
        conditions = [
            "s.ppe_status = 'helmet_off'",
            "s.verification_status = 'FINAL'"
        ]
        params = []

        if date_from:
            conditions.append("s.timestamp >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("s.timestamp <= ?")
            params.append(date_to)
        if worker_name:
            conditions.append("w.worker_name LIKE ?")
            params.append(f"%{worker_name}%")
        if department:
            conditions.append("w.department = ?")
            params.append(department)

        where_clause = "WHERE " + " AND ".join(conditions)

        sql = f"""
            SELECT s.*, w.worker_name, w.department
            FROM ppe_scans s
            LEFT JOIN workers w ON s.worker_id = w.worker_id
            {where_clause}
            ORDER BY s.timestamp DESC
            LIMIT ?
        """
        params.append(limit)
        return self._execute(sql, tuple(params), fetch=True)

    def get_violations_by_worker(self, date_from=None, date_to=None,
                                  worker_name=None, department=None):
        """
        Count helmet-off violations grouped by worker.

        Args:
            date_from:   Optional ISO date string for range start
            date_to:     Optional ISO date string for range end
            worker_name: Optional worker name filter (partial match)
            department:  Optional exact department filter

        Returns:
            List of dicts: [{worker_name, rfid_uid, department,
                             violation_count}]
        """
        conditions = [
            "s.ppe_status = 'helmet_off'",
            "s.verification_status = 'FINAL'"
        ]
        params = []

        if date_from:
            conditions.append("s.timestamp >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("s.timestamp <= ?")
            params.append(date_to)
        if worker_name:
            conditions.append("w.worker_name LIKE ?")
            params.append(f"%{worker_name}%")
        if department:
            conditions.append("w.department = ?")
            params.append(department)

        where_clause = "WHERE " + " AND ".join(conditions)

        sql = f"""
            SELECT
                COALESCE(w.worker_name, 'Unknown') as worker_name,
                s.rfid_uid,
                COALESCE(w.department, 'N/A') as department,
                COUNT(*) as violation_count
            FROM ppe_scans s
            LEFT JOIN workers w ON s.worker_id = w.worker_id
            {where_clause}
            GROUP BY s.rfid_uid
            ORDER BY violation_count DESC
        """
        return self._execute(sql, tuple(params), fetch=True)

    def get_daily_violations(self, days=30, date_from=None, date_to=None,
                              worker_name=None, department=None):
        """
        Get daily violation trend data.

        Args:
            days:        Default lookback window when no date range given
            date_from:   Optional ISO date string for range start
            date_to:     Optional ISO date string for range end
            worker_name: Optional worker name filter (partial match)
            department:  Optional exact department filter

        Returns:
            List of dicts: [{date, violation_count}]
        """
        conditions = [
            "s.ppe_status = 'helmet_off'",
            "s.verification_status = 'FINAL'"
        ]
        params = []

        if date_from:
            conditions.append("s.timestamp >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("s.timestamp <= ?")
            params.append(date_to)
        if worker_name:
            conditions.append("w.worker_name LIKE ?")
            params.append(f"%{worker_name}%")
        if department:
            conditions.append("w.department = ?")
            params.append(department)

        if not date_from and not date_to:
            conditions.append(
                f"date(s.timestamp) >= date('now', '-{int(days)} days')"
            )

        where_clause = "WHERE " + " AND ".join(conditions)

        # JOIN workers table when worker/department filters may be used
        sql = f"""
            SELECT
                date(s.timestamp) as date,
                COUNT(*) as violation_count
            FROM ppe_scans s
            LEFT JOIN workers w ON s.worker_id = w.worker_id
            {where_clause}
            GROUP BY date(s.timestamp)
            ORDER BY date(s.timestamp)
        """
        return self._execute(sql, tuple(params), fetch=True)

    def get_departments(self):
        """
        Get a list of all unique departments.

        Returns:
            List of department name strings
        """
        rows = self._execute(
            """SELECT DISTINCT department FROM workers
               WHERE department IS NOT NULL AND department != ''
               ORDER BY department""",
            fetch=True
        )
        return [r["department"] for r in rows]

    def get_scan_by_id(self, db_row_id):
        """
        Retrieve a single scan record by its database ID.

        Returns:
            dict or None
        """
        return self._execute(
            "SELECT * FROM ppe_scans WHERE id = ?",
            (db_row_id,), fetchone=True
        )

    def get_all_scans_for_export(self, date_from=None, date_to=None):
        """
        Retrieve all scans with worker info for CSV export.

        Returns:
            List of dicts with all relevant fields
        """
        conditions = []
        params = []

        if date_from:
            conditions.append("s.timestamp >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("s.timestamp <= ?")
            params.append(date_to)

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        sql = f"""
            SELECT
                s.id, s.scan_id, s.rfid_uid,
                COALESCE(w.worker_name, 'Unknown') as worker_name,
                COALESCE(w.department, 'N/A') as department,
                s.timestamp, s.access_status, s.ppe_status,
                s.verification_status, s.attempts, s.source
            FROM ppe_scans s
            LEFT JOIN workers w ON s.worker_id = w.worker_id
            {where_clause}
            ORDER BY s.timestamp DESC
        """
        return self._execute(sql, tuple(params), fetch=True)

    def get_access_distribution(self, date_from=None, date_to=None):
        """
        Get authorized vs denied scan counts.

        Returns:
            dict: {authorized: int, denied: int}
        """
        conditions = []
        params = []

        if date_from:
            conditions.append("timestamp >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("timestamp <= ?")
            params.append(date_to)

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        sql = f"""
            SELECT
                SUM(CASE WHEN access_status = 'AUTHORIZED' THEN 1 ELSE 0 END)
                    as authorized,
                SUM(CASE WHEN access_status = 'DENIED' THEN 1 ELSE 0 END)
                    as denied
            FROM ppe_scans
            {where_clause}
        """
        result = self._execute(sql, tuple(params), fetchone=True)
        return {
            "authorized": (result["authorized"] or 0) if result else 0,
            "denied": (result["denied"] or 0) if result else 0
        }
