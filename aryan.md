# Aryan's Presentation Notes — Demo & Wrap-Up

---

## 📝 TL;DR — Quick Summary

Aryan handles the **live demo, challenges, and future scope**. The demo covers **5 scenarios**: (1) a registered worker wearing a helmet — OLED shows "HELMET OK", 1× long buzz; (2) a registered worker without a helmet — OLED shows "NO HELMET !", 4× rapid beeps; (3) no person in frame — system retries up to 2 times with 3-second gaps, then gives 2× gentle beeps; (4) an unregistered RFID card — "ACCESS DENIED", 3× long beeps, no AI detection; (5) a full dashboard walkthrough across all 5 pages. Key challenges include non-blocking buzzer implementation, 5-frame majority voting to avoid false positives, CLAHE preprocessing for low-light face detection, and stale scan rejection via scan_id validation. Future scope ranges from GPU acceleration and multi-camera support to cloud sync, mobile dashboards, facial recognition, and full PPE detection (vests, gloves, goggles).

| Demo Scenario | What to Do | Expected OLED | Buzzer |
|--------------|-----------|--------------|--------|
| ✅ **Helmet ON** | Wear helmet + tap registered card | `HELMET OK` | 1× 2-second buzz |
| ❌ **Helmet OFF** | No helmet + tap registered card | `NO HELMET !` | 4× rapid beeps |
| 👤 **No Person** | Tap card + step away from camera | `STAND IN VIEW` | 2× gentle (after 3 retries) |
| 🚫 **Denied** | Tap unregistered card | `ACCESS DENIED` | 3× long beeps |
| 📊 **Dashboard** | Open browser, walk through 5 tabs | N/A | N/A |

| Topic | Key Points |
|-------|-----------|
| **Challenges** | Non-blocking buzzer, majority voting, CLAHE, stale scan rejection, UID normalization |
| **Future Scope** | GPU inference, multi-camera, cloud DB, mobile app, facial recognition, full PPE |
| **Aryan's Role** | Live demo → Challenges → Future scope → Q&A |

---

## 🎯 Transition from Vedant

> "Thanks, Vedant. Now I'll demonstrate the system live and walk you through each scenario the examiners should see."

---

## 1. System Flow Recap (What to Explain Before Starting Demo)

### Quick Flow Summary
```
RFID Tap → ESP32 reads UID → Python checks DB → Auth Result to ESP32
    → 5s countdown → AI detects helmet (5 frames, majority vote)
    → Result to ESP32 (OLED + Buzzer) → Logged to SQLite → Dashboard shows data
```

### The 4 Possible Outcomes
| # | Scenario | OLED Shows | Buzzer | DB Status |
|---|----------|-----------|--------|-----------|
| 1 | Registered worker WITH helmet | `HELMET OK` | 1× 2s long buzz | `helmet_on`, FINAL |
| 2 | Registered worker WITHOUT helmet | `NO HELMET !` | 4× rapid beeps | `helmet_off`, FINAL |
| 3 | Registered worker NOT in frame | `STAND IN VIEW` | 2× gentle (final only) | `no_person`, FINAL |
| 4 | Unregistered/deactivated card | `ACCESS DENIED` | 3× long beeps | DENIED |

---

## 2. Pre-Demo Setup Checklist

Before starting the demo, make sure all of these are running:

### ✅ Step 1: Hardware Setup
- [ ] ESP32 is powered on and connected to Wi-Fi
- [ ] RC522 RFID reader is wired correctly (SPI pins)
- [ ] OLED display shows "SCAN YOUR RFID CARD"
- [ ] Buzzer is connected to GPIO 4
- [ ] Webcam is connected to laptop (check which index — 0 or 1)
- [ ] RFID cards are ready (at least 1 registered + 1 unregistered)

### ✅ Step 2: Note ESP32 IP Address
- Open **Arduino IDE Serial Monitor** (115200 baud)
- Look for: `ESP32 IP: 192.168.x.x`
- Note this IP — you'll need it for the Python script

### ✅ Step 3: Start the Integration Script
```powershell
cd C:\Users\Aryan\Desktop\Smart_PPE_Monitoring
python ai/PPE_Helmet_Detection/ppe_integration.py --esp32-ip 192.168.x.x --show-camera
```
- Verify the console shows:
  - `Loading helmet model: last_hardhat_200_epochs.pt`
  - `Database ready: ppe_monitor.db`
  - `Webcam ready (1280x720)`
  - `ESP32 online: ESP32 PPE Monitor`
  - `Polling http://192.168.x.x/scan every 1.0s`

### ✅ Step 4: Start the Dashboard (separate terminal)
```powershell
cd C:\Users\Aryan\Desktop\Smart_PPE_Monitoring
streamlit run dashboard/app.py
```
- Opens at `http://localhost:8501`
- Verify it shows the Overview page with KPIs

### ✅ Step 5: Ensure Workers Are Registered
If the database is fresh, register at least one worker:
```powershell
python -c "
from database.db_manager import PPEDatabase
db = PPEDatabase()
db.initialize_database()
print(db.register_worker('69 A1 0D 07', 'Aryan Salunke', 'Safety'))
"
```
Or use the Dashboard → 👷 Workers → Register Worker form.

---

## 3. Demo Scenarios — Step by Step

### 🟢 SCENARIO 1: Compliant Worker (Helmet ON)

**What to do:**
1. Put on a **safety helmet**
2. Tap the **registered RFID card** on the RC522 reader
3. Watch the flow:

**What happens (narrate this):**
- **OLED:** "CHECKING... UID: 69 A1 0D 07" → "AUTHORIZED | WORKER: Aryan Salunke | PPE: AI PENDING"
- **Buzzer:** 2× short beeps (access granted)
- **Console:** Shows "NEW SCAN: #1 | UID: 69 A1 0D 07" → "[AUTH] AUTHORIZED — Worker: Aryan Salunke"
- **Camera preview:** Shows "POSITIONING | Get in front of camera: 5s... 4... 3... 2... 1..."
- **Console:** "Starting PPE detection..."
  - "Frame 1/5: helmet_on"
  - "Frame 2/5: helmet_on"
  - ... (5 frames)
  - "Majority vote: helmet_on (votes: {'helmet_on': 5})"
  - "Final result: helmet_on"
- **OLED:** "PPE: HELMET OK"
- **Buzzer:** 1× long continuous 2-second buzz ✅
- **Console:** "ESP32 accepted" → "Scan #1 complete: helmet_on"

**On Dashboard:** Refresh Overview → you'll see the scan appear in "Recent Activity" and compliance % update

---

### 🔴 SCENARIO 2: Non-Compliant Worker (Helmet OFF)

**What to do:**
1. **Remove the helmet** (or don't wear one)
2. Tap the **same registered RFID card**
3. Make sure your **face is clearly visible** to the camera

**What happens (narrate this):**
- Same auth flow: OLED → "AUTHORIZED" → 2× beeps
- 5-second countdown
- Detection:
  - "Frame 1/5: helmet_off" (YOLOv8 doesn't find helmet, Haar cascade finds face)
  - ... (5 frames, majority = `helmet_off`)
  - "Majority vote: helmet_off"
- **OLED:** "PPE: NO HELMET !" ❌
- **Buzzer:** 4× rapid beeps (urgent warning)
- **On Dashboard:** Shows as a violation in the 🚨 Violations tab

---

### 👤 SCENARIO 3: No Person Detected (Worker Not in Frame)

**What to do:**
1. Tap the registered RFID card
2. **Step away from the camera** or cover the webcam
3. Watch the retry behavior

**What happens (narrate this):**
- Auth flow as before → "AUTHORIZED"
- 5-second countdown
- **Attempt 1/3:** "Frame 1/5: no_person" → "Majority vote: no_person"
  - "Sending interim 'no_person' so OLED prompts worker..."
  - **OLED:** "PPE: STAND IN VIEW" (but **no buzzer** — interim only)
  - "Waiting 3s for worker to reposition..."
- **Attempt 2/3:** Still no person → same interim behavior → wait 3s
- **Attempt 3/3 (final):** Still no person → "Final result: no_person"
  - **OLED:** "STAND IN VIEW"
  - **Buzzer:** 2× gentle beeps (final alert)
- **Console:** "Scan #3 complete: no_person"

> **Point out to examiner:** "Notice how the system gives the worker 3 total chances (1 initial + 2 retries) before declaring 'no person'. The interim attempts update the OLED but suppress the buzzer to avoid unnecessary noise."

---

### 🚫 SCENARIO 4: Unregistered RFID Card (Access Denied)

**What to do:**
1. Tap an **RFID card that is NOT registered** in the database
2. Watch the denial flow

**What happens (narrate this):**
- **OLED:** "CHECKING..." → "ACCESS DENIED | UNKNOWN WORKER | UID: XX XX XX XX"
- **Buzzer:** 3× long warning beeps (500ms on, 500ms off)
- **Console:** "[AUTH] DENIED — Reason: unknown_uid, UID: XX XX XX XX"
- **No AI detection** happens (PPE check is skipped entirely for denied cards)
- **OLED** returns to "SCAN YOUR RFID CARD" after 8 seconds
- **Dashboard:** Scan appears in History with status "DENIED"

> **Point out:** "Access denied scans are still logged to the database for audit purposes, but the AI detection pipeline is never triggered — saving compute resources."

---

### 📊 SCENARIO 5: Dashboard Walkthrough

After running scenarios 1–4, switch to the browser and walk through:

1. **📊 Overview page:**
   - Show KPI cards: total scans, authorized count, denied count, compliance %
   - Show the daily compliance trend chart (point out the 80% target line)
   - Show the helmet-on vs helmet-off donut chart
   - Show the recent activity feed

2. **📋 Scan History page:**
   - Show the filterable table with all scan records
   - Demonstrate a filter: select "helmet_off" from PPE status dropdown
   - Point out the color-coded rows (green = compliant, red = violation)

3. **🚨 Violations page:**
   - Show the violations list (only `helmet_off` + `FINAL` scans)
   - Show "Violations by Worker" — which workers have the most violations
   - Show the daily violation trend chart

4. **👷 Workers page:**
   - Show the list of registered workers
   - Demonstrate **registering a new worker** (enter UID, name, department)
   - Show the **edit** and **deactivate** functionality
   - Point out: "Deactivating a worker preserves all their historical scans"

5. **📄 Reports page:**
   - Set a date range and show the filtered summary
   - Click "Download CSV" to show the export feature

---

## 4. Challenges Faced

### Hardware Challenges
| Challenge | How We Solved It |
|-----------|-----------------|
| **OLED flickering during buzzer** | Implemented non-blocking buzzer state machine (`updateBuzzer()`) instead of `delay()` calls — keeps the main loop responsive |
| **RFID read inconsistency** | Used `PICC_HaltA()` and `PCD_StopCrypto1()` after each read to properly reset the reader for the next scan |
| **ESP32 scan counter resets on reboot** | Database uses auto-increment IDs independent of ESP32's `scanCount`; Python tracks `last_processed_scan` per session |
| **SH1106 vs SSD1306 confusion** | Had to use `Adafruit_SH110X` library (not `SSD1306`) — different driver IC, same I2C interface |
| **OLED I2C on non-default pins** | Used `Wire.begin(SDA=21, SCL=25)` — ESP32 allows remapping I2C to any GPIO |

### Software / AI Challenges
| Challenge | How We Solved It |
|-----------|-----------------|
| **Single-frame false positives/negatives** | Implemented 5-frame majority voting — a single bad frame can't flip the result |
| **Poor lighting affects face detection** | Added CLAHE (Contrast Limited Adaptive Histogram Equalization) preprocessing before Haar cascade |
| **Profile faces not detected** | Added `haarcascade_profileface.xml` as a fallback when frontal face cascade returns no results |
| **Slow CPU inference (~4.7 FPS)** | Reduced inference size to 320px and limited to 5 frames — total detection takes ~1-2 seconds |
| **Worker not in frame during detection** | Added 5-second positioning countdown + 2 no-person retries with 3-second gaps |
| **Stale scan results from previous cards** | ESP32 validates `scan_id` on every POST — rejects results that don't match the current scan |
| **Database errors shouldn't crash detection** | Wrapped all DB calls in try/except with safe no-op fallbacks — detection continues even if DB fails |
| **UID format variations** | Created `_normalize_uid()` to handle spaces, colons, dashes, and case differences |

### Integration Challenges
| Challenge | How We Solved It |
|-----------|-----------------|
| **ESP32 HTTP server blocked during buzzer** | Non-blocking buzzer pattern using `millis()` — never uses `delay()` for PPE buzzer alerts |
| **Race condition: new scan during detection** | `recvScanId != scanCount` check rejects stale results (HTTP 409 Conflict) |
| **Authorization source of truth** | Moved from hardcoded UIDs on ESP32 to dynamic SQLite queries — single source of truth on the laptop |

---

## 5. Future Scope

### Short-Term Enhancements
- **GPU-accelerated inference** — Using CUDA-enabled PyTorch for real-time multi-person detection at 30+ FPS
- **Worker photo capture** — Save a snapshot of the worker's face/helmet on each scan for visual audit logs
- **Email/SMS violation alerts** — Notify supervisors immediately when a worker fails PPE compliance
- **Shift-based reporting** — Track compliance separately for morning, afternoon, and night shifts

### Medium-Term Enhancements
- **Multi-camera support** — Deploy multiple webcams at different entry points, all feeding into the same system
- **Multiple ESP32 gateways** — Scale to multiple checkpoints across a factory floor, each with its own RFID reader
- **Cloud database sync** — Migrate from local SQLite to Firebase/AWS DynamoDB for centralized, multi-site monitoring
- **Mobile dashboard** — Flutter or React Native app for supervisors to monitor compliance on-the-go

### Long-Term Vision
- **Full PPE detection** — Extend beyond helmets to detect safety vests, gloves, goggles, boots
- **Facial recognition** — Replace RFID with face-based worker identification (no cards needed)
- **Anomaly detection** — ML-based pattern recognition to flag unusual compliance drops before they become incidents
- **Integration with access control** — Physically lock turnstiles/gates until PPE compliance is confirmed
- **Edge computing** — Run YOLOv8 inference directly on an NVIDIA Jetson Nano mounted at the checkpoint, eliminating the need for a laptop

---

## 🗣️ Suggested Closing Talking Points

> - "We've demonstrated all four scenarios: compliant, non-compliant, no-person with retries, and access denied."
> - "The system has **316 automated tests** covering the database, integration logic, and dashboard."
> - "Our project is **modular and scalable** — the edge hardware, AI processing, and dashboard can each be upgraded independently."
> - "The biggest challenge was making the system **reliable in real-time** — the non-blocking buzzer, majority voting, and retry logic all contribute to robustness."
> - "Thank you for your time. We're happy to take any questions."

---

## 📌 Quick Commands Cheat Sheet (Keep Handy During Demo)

```powershell
# Start integration script (with camera preview)
python ai/PPE_Helmet_Detection/ppe_integration.py --esp32-ip 192.168.x.x --show-camera

# Start dashboard
streamlit run dashboard/app.py

# Register a worker quickly
python -c "from database.db_manager import PPEDatabase; db = PPEDatabase(); db.initialize_database(); print(db.register_worker('69 A1 0D 07', 'Aryan Salunke', 'Safety'))"

# Check database contents
python -c "from database.db_manager import PPEDatabase; db = PPEDatabase(); [print(w) for w in db.get_all_workers()]"

# Load demo data (if no hardware available)
python database/seed_demo_data.py

# Run all tests
python ai/PPE_Helmet_Detection/test_integration.py; python tests/test_database.py; python tests/test_integration_db.py; python tests/test_dashboard.py
```

---

## ⚠️ Common Demo Issues & Quick Fixes

| Problem | Quick Fix |
|---------|-----------|
| "ESP32 unreachable" | Check Wi-Fi — ESP32 and laptop must be on the same network. Reset ESP32. |
| "Cannot open webcam" | Try `--webcam 1` instead of default `--webcam 0`. Close any other app using the camera. |
| OLED shows nothing | Check I2C wiring (SDA=21, SCL=25). Verify 0x3C address. |
| RFID not reading | Check SPI wiring. Ensure card is within 3-5 cm. Try different card angle. |
| "Model not found" | Verify `ai/PPE_Helmet_Detection/models/last_hardhat_200_epochs.pt` exists. |
| Dashboard shows no data | Run at least one scan first, or load demo data with `python database/seed_demo_data.py`. |
| Face not detected (always no_person) | Improve lighting. Face the camera directly. Try removing glasses. |
