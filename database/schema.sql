-- ============================================================
-- Smart PPE Compliance Monitoring System — SQLite Schema
-- ============================================================
-- All timestamps use ISO 8601 format with local timezone info.
-- Example: 2026-10-01T10:30:00+05:30
-- The application uses the system's local timezone (IST / +05:30).
-- ============================================================

-- Workers table: Registered RFID card holders
CREATE TABLE IF NOT EXISTS workers (
    worker_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    rfid_uid    TEXT    UNIQUE NOT NULL,          -- Uppercase, space-separated hex (e.g. "69 A1 0D 07")
    worker_name TEXT    NOT NULL,
    department  TEXT,
    is_active   INTEGER DEFAULT 1,               -- 1 = active, 0 = deactivated
    created_at  TEXT    NOT NULL                  -- ISO 8601 timestamp
);

-- PPE scans table: Every RFID scan event (authorized and denied)
CREATE TABLE IF NOT EXISTS ppe_scans (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id             INTEGER,                         -- ESP32 scan counter (may reset on reboot)
    rfid_uid            TEXT    NOT NULL,                 -- Scanned RFID UID
    worker_id           INTEGER,                         -- FK to workers (NULL for unknown cards)
    timestamp           TEXT    NOT NULL,                 -- ISO 8601 scan timestamp
    access_status       TEXT    NOT NULL,                 -- 'AUTHORIZED' or 'DENIED'
    ppe_status          TEXT,                             -- 'helmet_on', 'helmet_off', 'no_person', 'verification_error'
    verification_status TEXT    NOT NULL,                 -- 'PENDING', 'FINAL', 'FAILED', 'DENIED'
    attempts            INTEGER DEFAULT 0,               -- Number of AI detection attempts
    source              TEXT    DEFAULT 'ESP32',          -- Origin of the scan event

    FOREIGN KEY (worker_id) REFERENCES workers(worker_id)
        ON DELETE SET NULL
);

-- ============================================================
-- Indexes for common query patterns (dashboard, filtering)
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_scans_timestamp       ON ppe_scans(timestamp);
CREATE INDEX IF NOT EXISTS idx_scans_rfid_uid        ON ppe_scans(rfid_uid);
CREATE INDEX IF NOT EXISTS idx_scans_worker_id       ON ppe_scans(worker_id);
CREATE INDEX IF NOT EXISTS idx_scans_access_status   ON ppe_scans(access_status);
CREATE INDEX IF NOT EXISTS idx_scans_ppe_status      ON ppe_scans(ppe_status);
CREATE INDEX IF NOT EXISTS idx_scans_verification    ON ppe_scans(verification_status);
CREATE INDEX IF NOT EXISTS idx_workers_rfid_uid      ON workers(rfid_uid);
CREATE INDEX IF NOT EXISTS idx_workers_active        ON workers(is_active);
