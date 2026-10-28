# REDSTONE: An AI-Based Smart PPE Compliance Monitoring System

An Industrial IoT system that uses **ESP32**, **RFID**, **YOLOv8**, **OpenCV**, **SQLite** and **Streamlit** to monitor Personal Protective Equipment (PPE) compliance in industrial environments.

## System Overview

```
┌─────────────┐     RFID Scan     ┌─────────────┐    HTTP API    ┌──────────────┐
│  RFID Card  │ ─────────────────>│   ESP32 +   │<──────────────>│   Laptop     │
│  (Worker)   │                   │  RC522 +    │               │  Python +    │
└─────────────┘                   │  OLED +     │               │  YOLOv8 +    │
                                  │  Buzzer     │               │  Webcam      │
                                  └──────┬──────┘               └──────┬───────┘
                                         │                             │
                                    OLED Display                  SQLite DB
                                    Buzzer Alert                       │
                                                                ┌──────┴───────┐
                                                                │  Streamlit   │
                                                                │  Dashboard   │
                                                                └──────────────┘
```

### Workflow

1. Worker scans RFID card on the ESP32 reader
2. ESP32 authorizes or denies the card based on registered UIDs
3. For authorized cards, the Python application starts a 5-second positioning countdown
4. YOLOv8 helmet detection runs on the laptop webcam (5-frame majority voting)
5. If no person detected, up to 2 retries with 3-second repositioning intervals
6. Result sent to ESP32 → OLED display + buzzer alert
7. All scan events logged to local SQLite database
8. Streamlit dashboard shows compliance statistics, violations, and worker management

### PPE Detection States

| Status              | Meaning                          | ESP32 OLED     | Buzzer              |
|---------------------|----------------------------------|----------------|---------------------|
| `helmet_on`         | Worker wearing helmet (compliant)| HELMET OK      | 1× 2-second buzz    |
| `helmet_off`        | No helmet detected (violation)   | NO HELMET !    | 4× rapid beeps      |
| `no_person`         | No person in camera view         | STAND IN VIEW  | 2× gentle beeps¹    |
| `verification_error`| Camera/inference failure         | VERIFY ERROR   | No buzzer            |

¹ Buzzer only on final attempt after all retries

## Hardware Requirements

- **ESP32 WROOM / DOIT ESP32 DEVKIT V1**
- **RC522 RFID Reader** (SPI)
- **1.3-inch SH1106 I2C OLED** (128×64, address 0x3C)
- **Buzzer** (GPIO4)
- **Laptop** with webcam (built-in or external)
- **RFID cards** (Mifare compatible)

### ESP32 Pin Configuration

| Component   | Pin     | GPIO |
|-------------|---------|------|
| RFID SS     | GPIO5   | 5    |
| RFID RST    | GPIO22  | 22   |
| RFID SCK    | GPIO18  | 18   |
| RFID MISO   | GPIO19  | 19   |
| RFID MOSI   | GPIO23  | 23   |
| Buzzer      | GPIO4   | 4    |
| OLED SDA    | GPIO21  | 21   |
| OLED SCL    | GPIO25  | 25   |

## Software Requirements

- **Python 3.13+**
- **Arduino IDE** (for ESP32 firmware)
- Windows 10/11

### Python Dependencies

```
ultralytics       # YOLOv8
opencv-python     # OpenCV
torch             # PyTorch (CPU)
numpy
requests
pandas
streamlit
plotly
```

Install all dependencies:

```powershell
pip install ultralytics opencv-python torch numpy requests pandas streamlit plotly
```

## Project Structure

```
Smart_PPE_Monitoring/
├── ai/
│   └── PPE_Helmet_Detection/
│       ├── ppe_integration.py          # Main integration script
│       ├── helmet_webcam_test.py       # Standalone webcam test
│       ├── test_integration.py         # Original integration tests (89 tests)
│       └── models/
│           ├── last_hardhat_200_epochs.pt  # Custom YOLOv8 helmet model
│           └── yolov8x.pt                 # COCO model (future use)
├── database/
│   ├── db_manager.py                   # SQLite database manager
│   ├── schema.sql                      # Database schema
│   ├── seed_demo_data.py              # Optional demo data generator
│   ├── __init__.py                     # Package init
│   └── ppe_monitor.db                  # SQLite database (auto-created)
├── dashboard/
│   └── app.py                          # Streamlit dashboard
├── esp32/
│   └── Code/
│       └── rc522_buzzer_oled_wifi/
│           └── rc522_buzzer_oled_wifi.ino  # ESP32 firmware
├── tests/
│   ├── test_database.py               # Database module tests (122 tests)
│   ├── test_integration_db.py         # DB integration tests (41 tests)
│   └── test_dashboard.py             # Dashboard tests (64 tests)
└── README.md                          # This file
```

## Database Schema

### Workers Table

| Column      | Type         | Description                     |
|-------------|--------------|---------------------------------|
| worker_id   | INTEGER PK   | Auto-increment worker ID        |
| rfid_uid    | TEXT UNIQUE   | RFID card UID (e.g. "69 A1 0D 07") |
| worker_name | TEXT         | Worker display name              |
| department  | TEXT         | Department or work area          |
| is_active   | INTEGER      | 1 = active, 0 = deactivated     |
| created_at  | TEXT         | ISO 8601 registration timestamp  |

### PPE Scans Table

| Column              | Type         | Description                        |
|---------------------|--------------|------------------------------------|
| id                  | INTEGER PK   | Auto-increment scan record ID      |
| scan_id             | INTEGER      | ESP32 scan counter                 |
| rfid_uid            | TEXT         | Scanned RFID UID                   |
| worker_id           | INTEGER FK   | Associated worker (nullable)       |
| timestamp           | TEXT         | ISO 8601 scan timestamp            |
| access_status       | TEXT         | AUTHORIZED or DENIED               |
| ppe_status          | TEXT         | helmet_on/helmet_off/no_person/verification_error |
| verification_status | TEXT         | PENDING, FINAL, FAILED, or DENIED  |
| attempts            | INTEGER      | Number of AI detection attempts    |
| source              | TEXT         | Scan origin (default: ESP32)       |

All timestamps use **ISO 8601** format with local timezone offset (e.g., `2026-10-01T10:30:00+05:30`).

## Setup and Usage

### 1. Initialize the Database

The database is automatically created on first run. To manually initialize:

```powershell
cd Smart_PPE_Monitoring
python -c "from database.db_manager import PPEDatabase; db = PPEDatabase(); db.initialize_database(); print('Database initialized')"
```

### 2. Register Workers

Workers can be registered through the Streamlit dashboard (👷 Workers → Register Worker) or via Python:

```powershell
python -c "
from database.db_manager import PPEDatabase
db = PPEDatabase()
db.initialize_database()
print(db.register_worker('69 A1 0D 07', 'Aryan Salunke', 'Safety'))
print(db.register_worker('A4 58 27 07', 'Rohan Patil', 'Operations'))
"
```

### 3. Flash ESP32 Firmware

1. Open `esp32/Code/rc522_buzzer_oled_wifi/rc522_buzzer_oled_wifi.ino` in Arduino IDE
2. Update Wi-Fi credentials (lines 11-12) with your network details
3. Select board: **DOIT ESP32 DEVKIT V1**
4. Upload to ESP32
5. Note the IP address printed on Serial Monitor (115200 baud)

### 4. Start the Integration Script

```powershell
cd Smart_PPE_Monitoring

# Basic (no camera preview)
python ai/PPE_Helmet_Detection/ppe_integration.py --esp32-ip 192.168.1.100

# With camera preview
python ai/PPE_Helmet_Detection/ppe_integration.py --esp32-ip 192.168.1.100 --show-camera

# With external webcam (index 1)
python ai/PPE_Helmet_Detection/ppe_integration.py --esp32-ip 192.168.1.100 --show-camera --webcam 1
```

Replace `192.168.1.100` with your ESP32's actual IP address.

### 5. Start the Streamlit Dashboard

```powershell
cd Smart_PPE_Monitoring
streamlit run dashboard/app.py
```

The dashboard opens at `http://localhost:8501`.

### 6. (Optional) Load Demo Data

To preview the dashboard without hardware:

```powershell
python database/seed_demo_data.py
streamlit run dashboard/app.py
```

## Running Tests

### All Tests

```powershell
cd Smart_PPE_Monitoring

# Original integration tests (89 tests)
python ai/PPE_Helmet_Detection/test_integration.py

# Database module tests (122 tests)
python tests/test_database.py

# Database integration tests (41 tests)
python tests/test_integration_db.py

# Dashboard tests (64 tests)
python tests/test_dashboard.py
```

### Run All Tests at Once

```powershell
cd Smart_PPE_Monitoring
python ai/PPE_Helmet_Detection/test_integration.py; python tests/test_database.py; python tests/test_integration_db.py; python tests/test_dashboard.py
```

**Total: 316 automated software tests**

## Dashboard Features

### 📊 Overview
- KPI cards: Total scans, authorized, denied, compliance %, helmet on/off, failures
- Daily compliance trend chart (with 80% target line)
- Helmet-on vs helmet-off distribution (donut chart)
- Access authorized vs denied distribution
- Recent activity feed

### 📋 Scan History
- Filterable table of all scan records
- Filters: date range, worker name, department, PPE status, access status
- Color-coded rows (green = compliant, red = violation/denied)
- Manual refresh button

### 🚨 Violations
- Helmet-off incident tracking
- Violations grouped by worker
- Daily violation trend chart
- Filterable violation records table

### 👷 Worker Management
- Register new workers with RFID UID, name, department
- View all workers with status
- Edit worker details
- Activate/deactivate workers (preserves historical scan data)
- Duplicate RFID UID prevention

### 📄 Reports
- Date-range filtered reports
- Period summary metrics
- CSV export of scan data
- Compliance breakdown chart

## Compliance Calculation

```
Compliance % = helmet_on / (helmet_on + helmet_off) × 100
```

**Excluded from the denominator:**
- `no_person` scans
- `verification_error` scans
- PENDING scans
- DENIED scans

Division by zero is handled safely (returns 0.0%).

## Backup and Restore

### Backup the Database

```powershell
# Copy the database file
Copy-Item "database\ppe_monitor.db" "database\ppe_monitor_backup_$(Get-Date -Format 'yyyyMMdd').db"
```

### Restore from Backup

```powershell
# Replace the database with a backup
Copy-Item "database\ppe_monitor_backup_20261001.db" "database\ppe_monitor.db" -Force
```

### Reset the Database

```powershell
# Delete the database (will be recreated on next run)
Remove-Item "database\ppe_monitor.db" -Force
```

**Important:** The database file `ppe_monitor.db` contains all historical scan and worker data. Always backup before making changes.

## Known Limitations

1. **ESP32 scan counter resets on reboot** — The ESP32 `scanCount` resets to 0 on power cycle. The database uses auto-increment IDs, so duplicate `scan_id` values from different sessions are stored as separate records. The application uses a `last_processed_scan` counter to avoid re-processing within a single session.

2. **No persistent event identifier** — The ESP32 does not provide a globally unique event ID. Within a single session, `scan_id > last_processed_scan` prevents duplicates. After an ESP32 restart, the first scan may have a `scan_id` lower than `last_processed_scan`, which is handled by the Python script's session-level tracking.

3. **Single-user dashboard** — The Streamlit dashboard is designed for single-user access on localhost. It does not support concurrent multi-user sessions.

4. **CPU inference speed** — YOLOv8 runs at ~4.7 FPS on CPU. Sufficient for single-person compliance checks but not for real-time multi-person tracking.

5. **No image storage** — Webcam frames are not saved to the database. Only detection results and metadata are recorded.

6. **Dashboard refresh** — The dashboard queries SQLite on page load or manual refresh. It does not receive live push events from the integration script.

7. **Single camera, single person** — The system cannot determine which person is wearing a helmet when multiple people are in frame.

## Future Enhancements

- Cloud database sync (Firebase / AWS)
- Multi-camera support
- Worker photo capture on scan
- Email/SMS violation alerts
- Shift-based compliance reporting
- GPU-accelerated inference
- Mobile dashboard
- Multiple ESP32 gateway support

## License

This is a final-year engineering project. All rights reserved.

---

**Project:** AI-Based Smart PPE Compliance Monitoring System (Industrial IoT)
**Author:** Aryan Salunke
**Technologies:** ESP32 • RFID • YOLOv8 • OpenCV • SQLite • Streamlit
