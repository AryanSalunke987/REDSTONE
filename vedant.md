# Vedant's Presentation Notes

---

## 📝 TL;DR — Quick Summary

Vedant presents the **hardware, sensors, actuators, software stack, and detailed working flow** of the Smart PPE Monitoring System. The hardware layer consists of an **ESP32 WROOM** microcontroller connected to an **RC522 RFID reader** (SPI, 13.56 MHz) for worker identification, a **1.3" SH1106 OLED** (I2C, 128×64) for status display, a **piezo buzzer** (GPIO4) for audio alerts with 5 distinct patterns, and a **USB webcam** (720p) for AI inference. The software stack uses **Arduino C++** on the ESP32 (7 libraries), **Python 3.13+** with **YOLOv8** (custom 200-epoch hardhat model) and **OpenCV** Haar cascades for three-state detection (helmet_on / helmet_off / no_person), **SQLite** with 2 tables and 6 indexes for logging, and a **Streamlit + Plotly** dashboard with 5 pages. The system uses a 5-frame majority vote, a 5-second positioning countdown, and up to 2 no-person retries. All 316 tests are automated.

| Component | Technology | Protocol / Details |
|-----------|-----------|-------------------|
| **Microcontroller** | ESP32 WROOM (DOIT DEVKIT V1) | Wi-Fi HTTP server, 4 endpoints |
| **RFID Reader** | RC522 (Mifare, 13.56 MHz) | SPI — SS:5, RST:22, SCK:18, MISO:19, MOSI:23 |
| **Display** | SH1106 OLED (128×64, 1.3") | I2C — SDA:21, SCL:25, addr 0x3C |
| **Buzzer** | Piezo buzzer, 2 kHz | GPIO 4, non-blocking state machine |
| **Camera** | USB Webcam (1280×720) | Connected to laptop |
| **AI Model** | YOLOv8 (200 epochs, hardhat) | CPU inference, conf ≥ 0.45, 320px |
| **Face Detection** | Haar Cascades (frontal + profile) | OpenCV + CLAHE preprocessing |
| **Database** | SQLite 3 (WAL mode) | 2 tables (workers, ppe_scans), 6 indexes |
| **Dashboard** | Streamlit + Plotly | 5 pages, dark theme, CSV export |
| **Testing** | unittest (Python) | 316 tests across 4 files |
| **Vedant's Role** | Sensors/actuators → Software → Technologies → Working flow |

---

## 🎯 Transition from Sudeep

> "As Sudeep explained the problem and architecture, I'll now walk you through the **actual hardware components, sensors, actuators, and software technologies** we've used, followed by the **detailed working flow** of the system."

---

## 1. Hardware Components — Sensors & Actuators

### 1.1 ESP32 WROOM / DOIT ESP32 DEVKIT V1 (Microcontroller)
- **Role:** Central IoT gateway — connects all peripherals and communicates with the laptop over Wi-Fi
- **Key specs:**
  - Dual-core Xtensa LX6 processor @ 240 MHz
  - Built-in **Wi-Fi** (802.11 b/g/n) — used for HTTP communication with the laptop
  - 520 KB SRAM, 4 MB Flash
  - Multiple SPI, I2C, GPIO interfaces
- **In our project:** Runs an HTTP web server with 4 endpoints (`/`, `/scan`, `/auth_result`, `/ppe_result`), reads RFID, drives OLED and buzzer

### 1.2 RC522 RFID Reader (Sensor — Input)
- **Role:** Reads RFID card UIDs for **worker identification**
- **Protocol:** SPI (Serial Peripheral Interface)
- **Operating frequency:** 13.56 MHz (Mifare standard)
- **Read range:** ~3–5 cm
- **Pin connections on ESP32:**
  | Pin | GPIO |
  |-----|------|
  | SS (SDA) | GPIO 5 |
  | RST | GPIO 22 |
  | SCK | GPIO 18 |
  | MISO | GPIO 19 |
  | MOSI | GPIO 23 |
- **Cards used:** Mifare Classic compatible RFID cards/tags
- **UID format:** 4-byte hex, e.g., `69 A1 0D 07`

### 1.3 SH1106 1.3" OLED Display (Actuator — Output)
- **Role:** Shows real-time **status messages** to the worker (authorized/denied, helmet status)
- **Protocol:** I2C
- **Resolution:** 128×64 pixels, monochrome (white on black)
- **I2C address:** 0x3C
- **Pin connections:**
  | Pin | GPIO |
  |-----|------|
  | SDA | GPIO 21 |
  | SCL | GPIO 25 |
- **Display layout:** 4-line screen:
  - Line 1: Header ("PPE MONITORING") with separator line
  - Line 2: RFID status (AUTHORIZED / DENIED / CHECKING)
  - Line 3: Worker name or UID
  - Line 4: PPE result (HELMET OK / NO HELMET / STAND IN VIEW)
- **Auto-return:** Screen returns to "SCAN YOUR RFID CARD" after 8 seconds

### 1.4 Buzzer (Actuator — Output)
- **Role:** **Audio alerts** for different events
- **Pin:** GPIO 4
- **Frequency:** 2000 Hz tone
- **Alert patterns:**

| Event | Pattern | Description |
|-------|---------|-------------|
| Access Granted | 2× short beeps (200ms on, 150ms off) | Confirms RFID authorization |
| Access Denied | 3× long beeps (500ms on, 500ms off) | Warns unauthorized card |
| Helmet ON (Compliant) | 1× continuous 2-second buzz | Confirms PPE compliance |
| Helmet OFF (Violation) | 4× rapid beeps (100ms on, 100ms off) | Urgent violation alert |
| No Person (Final) | 2× gentle beeps (150ms on, 200ms off) | Prompt to reposition |

- **Non-blocking implementation:** Uses a state machine (`updateBuzzer()`) so the ESP32's HTTP server stays responsive during buzzer patterns

### 1.5 Webcam (Sensor — Input)
- **Role:** Captures video frames for **AI-based helmet detection**
- **Resolution:** 1280×720 (720p)
- **Location:** Connected to the laptop (built-in or external USB webcam)
- **Index:** Configurable via `--webcam 0` or `--webcam 1` command-line argument

### 1.6 RFID Cards / Tags (Passive Component)
- **Type:** Mifare Classic compatible (13.56 MHz)
- **Each card has a unique UID** — mapped to a worker in the database
- **No data is written** to the card — only the UID is read

---

## 2. Software & Technologies

### 2.1 ESP32 Firmware (Arduino C++)
- **IDE:** Arduino IDE
- **Libraries used:**
  | Library | Purpose |
  |---------|---------|
  | `WiFi.h` | Wi-Fi connectivity |
  | `WebServer.h` | HTTP server on ESP32 |
  | `SPI.h` | SPI communication for RFID |
  | `MFRC522.h` | RC522 RFID reader driver |
  | `Wire.h` | I2C communication for OLED |
  | `Adafruit_GFX.h` | Graphics primitives for OLED |
  | `Adafruit_SH110X.h` | SH1106 OLED display driver |
- **HTTP endpoints exposed by ESP32:**
  | Endpoint | Method | Purpose |
  |----------|--------|---------|
  | `/` | GET | Health check — confirms system is online |
  | `/scan` | GET | Returns latest RFID scan data as JSON |
  | `/auth_result` | POST | Receives authorization decision from Python |
  | `/ppe_result` | POST | Receives AI detection result from Python |

### 2.2 Python Integration Script
- **Python version:** 3.13+
- **Key libraries:**
  | Library | Version/Role |
  |---------|-------------|
  | `ultralytics` | YOLOv8 object detection framework |
  | `opencv-python` (cv2) | Image processing, Haar cascades, webcam capture |
  | `torch` (PyTorch) | Deep learning inference backend (CPU) |
  | `numpy` | Numerical operations for image arrays |
  | `requests` | HTTP communication with ESP32 |
- **Key parameters (configurable):**
  | Parameter | Value | Purpose |
  |-----------|-------|---------|
  | `CONFIDENCE_THRESHOLD` | 0.45 | Minimum YOLOv8 detection confidence |
  | `INFERENCE_SIZE` | 320px | Input image size for YOLO |
  | `VOTE_FRAMES` | 5 | Frames for majority voting |
  | `POLL_INTERVAL` | 1.0s | ESP32 polling frequency |
  | `NO_PERSON_RETRIES` | 2 | Retry attempts for no-person |
  | `RETRY_DELAY` | 3.0s | Gap between retries |
  | `POSITIONING_DELAY_SECONDS` | 5s | Countdown before detection |

### 2.3 AI / Machine Learning — YOLOv8
- **Model:** YOLOv8 (You Only Look Once, version 8) by Ultralytics
- **Training:** Custom model trained for **200 epochs** on a **hardhat detection dataset**
- **Model file:** `last_hardhat_200_epochs.pt` (~6.5 MB)
- **Classes detected:** Hardhat/Helmet presence
- **Inference:** CPU-based (~4.7 FPS) — sufficient for single-person checkpoint use
- **Supplementary detection:** OpenCV **Haar Cascade** classifiers for face detection:
  - `haarcascade_frontalface_alt2.xml` — frontal face
  - `haarcascade_profileface.xml` — side/profile face
  - **CLAHE** (Contrast Limited Adaptive Histogram Equalization) — enhances images in poor lighting

### 2.4 Three-State Detection Logic
```
IF helmet detected (YOLOv8) → "helmet_on"    (Compliant ✅)
ELSE IF face detected (Haar) → "helmet_off"  (Violation ❌)
ELSE                         → "no_person"   (Retry 👤)
```
> This logic ensures: if YOLO sees a helmet → compliant. If no helmet but a face is visible → violation. If neither → no one is in frame.

### 2.5 SQLite Database
- **Engine:** SQLite 3 (Python built-in `sqlite3` module)
- **Database file:** `database/ppe_monitor.db` (auto-created)
- **Schema — 2 tables:**

**workers table:**
| Column | Type | Purpose |
|--------|------|---------|
| worker_id | INTEGER PK | Auto-increment ID |
| rfid_uid | TEXT UNIQUE | Normalized RFID UID |
| worker_name | TEXT | Display name |
| department | TEXT | Work area |
| is_active | INTEGER | 1=active, 0=deactivated |
| created_at | TEXT | ISO 8601 timestamp |

**ppe_scans table:**
| Column | Type | Purpose |
|--------|------|---------|
| id | INTEGER PK | Auto-increment record ID |
| scan_id | INTEGER | ESP32 scan counter |
| rfid_uid | TEXT | Scanned UID |
| worker_id | INTEGER FK | Links to workers table |
| timestamp | TEXT | ISO 8601 scan time |
| access_status | TEXT | AUTHORIZED or DENIED |
| ppe_status | TEXT | helmet_on / helmet_off / no_person / verification_error |
| verification_status | TEXT | PENDING / FINAL / FAILED / DENIED |
| attempts | INTEGER | Number of AI detection attempts |
| source | TEXT | Origin (default: ESP32) |

- **Performance settings:** WAL journal mode, foreign keys ON, 6 indexes for fast queries

### 2.6 Streamlit Dashboard
- **Framework:** Streamlit (Python web framework for data apps)
- **Visualization:** Plotly Express + Plotly Graph Objects
- **Data handling:** Pandas DataFrames
- **Theme:** Dark mode with industrial color palette
- **5 Pages:**
  1. **📊 Overview** — KPI cards, daily compliance trend (with 80% target line), donut charts, recent activity
  2. **📋 Scan History** — Filterable table of all scans (date range, worker, department, status filters)
  3. **🚨 Violations** — Helmet-off incident tracking, violations by worker, daily violation trend
  4. **👷 Workers** — Register new workers, edit details, activate/deactivate, duplicate UID prevention
  5. **📄 Reports** — Date-range reports, period summary, CSV export

### 2.7 Testing
- **316 total automated tests** across 4 test files:
  | Test File | Tests | Covers |
  |-----------|-------|--------|
  | `test_integration.py` | 89 | ESP32 ↔ Python communication, detection logic |
  | `test_database.py` | 122 | All database CRUD operations |
  | `test_integration_db.py` | 41 | End-to-end DB integration |
  | `test_dashboard.py` | 64 | Dashboard rendering and logic |

---

## 3. Actual Working Flow (Detailed Technical Flow)

### Phase 1: System Startup
1. **ESP32 boots** → initializes OLED ("INITIALIZING..."), SPI (RFID), I2C (OLED), connects to Wi-Fi
2. ESP32 starts **HTTP server** on port 80, displays "SCAN YOUR RFID CARD" on OLED
3. **Python script starts** (`ppe_integration.py --esp32-ip <IP> --show-camera`)
   - Loads YOLOv8 model + Haar cascades
   - Initializes SQLite database (creates tables if needed)
   - Opens webcam at 1280×720
   - Tests ESP32 connection via GET to `/`
   - Begins polling loop

### Phase 2: RFID Scan & Authorization
4. **Worker taps RFID card** on RC522 reader
5. ESP32 reads 4-byte UID → `latestUID = "69 A1 0D 07"`, `scanCount++`, `access = "WAITING"`
6. OLED shows: "CHECKING... UID: 69 A1 0D 07"
7. Python detects new scan (`scan_id > last_processed_scan && access == "WAITING"`)
8. Python calls `check_authorization(db, uid)`:
   - Normalizes UID format (handles spaces, colons, dashes, case)
   - Queries `SELECT * FROM workers WHERE rfid_uid = ?`
   - Checks `is_active == 1`
9. Python sends **POST /auth_result** with `{scan_id, authorized, worker_name}`
10. ESP32 receives response:
    - **AUTHORIZED:** OLED shows "AUTHORIZED | WORKER: Aryan Salunke | PPE: AI PENDING", 2× access beeps
    - **DENIED:** OLED shows "ACCESS DENIED | UNKNOWN WORKER | UID: XX XX XX XX", 3× denial beeps, OLED returns to ready after 8s

### Phase 3: Positioning & AI Detection (Authorized Only)
11. Python runs **5-second positioning countdown** (console + camera overlay: "Get in front of camera: 5s... 4s... 3s...")
12. Detection begins — `majority_vote()`:
    - **Frame 1/5:** Capture → YOLOv8 inference → Haar face detection → Vote: `helmet_on`
    - **Frame 2/5:** Capture → inference → Vote: `helmet_on`
    - **Frame 3/5:** Capture → inference → Vote: `helmet_off`
    - **Frame 4/5:** Capture → inference → Vote: `helmet_on`
    - **Frame 5/5:** Capture → inference → Vote: `helmet_on`
    - **Result:** `helmet_on` wins 4-1 → **COMPLIANT**

### Phase 4: Result Delivery & Logging
13. Python sends **POST /ppe_result** with `{scan_id, status: "helmet_on", final: true}`
14. ESP32 updates OLED: "PPE: HELMET OK" and plays 1× 2-second confirmation buzz
15. Python writes to SQLite: `UPDATE ppe_scans SET ppe_status='helmet_on', verification_status='FINAL', attempts=1`
16. OLED auto-returns to "SCAN YOUR RFID CARD" after 8 seconds
17. System is ready for the next scan

### Phase 5: No-Person Retry Flow
- If majority vote = `no_person` (attempt 1 of 3):
  - Python sends `POST /ppe_result` with `{status: "no_person", final: false}` → OLED shows "STAND IN VIEW" but **no buzzer** (interim)
  - Waits 3 seconds for worker to reposition
  - Runs detection again (attempt 2)
  - If still `no_person` (attempt 2 of 3): same interim behavior, wait 3s, retry
  - If `no_person` on final attempt (3 of 3): sends `final: true` → buzzer plays 2× gentle beeps

---

## 🗣️ Suggested Talking Points

> - "We chose the **ESP32** for its built-in Wi-Fi and rich GPIO — it acts as both the RFID reader interface and a web server."
> - "The **YOLOv8 model** was custom-trained for 200 epochs specifically on hardhat images — it's not a generic object detector."
> - "We use **two detection methods together** — YOLOv8 for helmets and Haar cascades for faces — to create a robust three-state logic."
> - "The **buzzer uses a non-blocking state machine** so the ESP32 can still respond to HTTP requests while playing alert sounds."
> - "All timestamps are in **ISO 8601 with timezone** — this ensures consistency when the dashboard queries historical data."
> - "Now I'll hand over to **Aryan**, who will demonstrate the system live and walk through each scenario."

---

## 📌 Quick Reference — Component Summary

| Layer | Components | Protocol |
|-------|-----------|----------|
| **Sensing** | RC522 RFID, Webcam | SPI, USB |
| **Processing** | ESP32, Python/YOLOv8 | Wi-Fi HTTP |
| **Output** | SH1106 OLED, Buzzer | I2C, GPIO |
| **Storage** | SQLite (ppe_monitor.db) | File-based |
| **Visualization** | Streamlit + Plotly | HTTP (port 8501) |
