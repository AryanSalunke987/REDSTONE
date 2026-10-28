# Sudeep's Presentation Notes

---

## 📝 TL;DR — Quick Summary

Our project is an **AI-Based Smart PPE Compliance Monitoring System** — an Industrial IoT solution that automates helmet compliance checks at industrial entry gates. A worker taps their **RFID card** on an **ESP32-based reader**, which communicates over Wi-Fi with a **Python script** running **YOLOv8 helmet detection** via a webcam. The system gives instant feedback through an **OLED display** and **buzzer alerts**, logs every scan event to a local **SQLite database**, and provides a **Streamlit web dashboard** for compliance analytics, violation tracking, and worker management. Authorization is dynamic (database-driven, not hardcoded), detection uses 5-frame majority voting for accuracy, and the system retries up to 2 times if no person is detected. Sudeep covers the problem statement, use cases, architecture, and general flow.

| What | Details |
|------|---------|
| **Project** | AI-Based Smart PPE Compliance Monitoring System |
| **Domain** | Industrial IoT + Computer Vision |
| **Hardware** | ESP32 + RC522 RFID + SH1106 OLED + Buzzer + Webcam |
| **AI Model** | YOLOv8 (200 epochs, hardhat dataset) |
| **Software** | Python, OpenCV, PyTorch, SQLite, Streamlit |
| **Detection** | 5-frame majority vote → helmet_on / helmet_off / no_person |
| **Dashboard** | 5 pages — Overview, Scan History, Violations, Workers, Reports |
| **Tests** | 316 automated tests |
| **Sudeep's Role** | Problem statement → Use cases → Architecture → General flow |

---

## 🎯 Opening & Introduction

> "Good morning/afternoon. We are presenting our final-year project — **AI-Based Smart PPE Compliance Monitoring System** — an Industrial IoT solution for workplace safety."

---

## 1. Problem Statement

### The Problem
- In industrial environments (construction sites, factories, warehouses), workers are **required to wear PPE** — particularly **safety helmets** — to prevent head injuries.
- Current compliance monitoring is **manual** — supervisors physically check workers, which is:
  - **Inconsistent** — not all workers are checked every time
  - **Time-consuming** — supervisors can only be in one place at a time
  - **Unverifiable** — no digital record of who was compliant and when
  - **Reactive, not preventive** — violations are caught after accidents, not before

### The Need
- **Automated, real-time PPE detection** at entry/checkpoint gates
- **Worker identification** tied to compliance checks (who was wearing what, and when)
- **Digital logging** of all events for audits, reports, and trend analysis
- **Instant feedback** to the worker — allow if compliant, alert if not

### Our Solution
> An integrated system that uses **RFID for worker identification**, **AI-based computer vision (YOLOv8) for helmet detection**, and a **web dashboard for monitoring** — all connected through an **ESP32 IoT gateway**.

---

## 2. Use Cases

### Primary Use Case — Entry Gate PPE Check
1. A worker approaches the checkpoint and taps their **RFID card**
2. The system **identifies the worker** from the database
3. A **camera captures the worker** and AI determines if they are wearing a helmet
4. **Immediate feedback** is given — green signal if compliant, alarm if not
5. The event is **logged** with timestamp, worker name, and result

### Secondary Use Cases
- **Compliance Reporting** — Management can view daily/weekly/monthly compliance rates
- **Violation Tracking** — Identify repeat offenders for targeted safety training
- **Worker Management** — Register/deactivate workers, manage departments
- **Audit Trail** — Complete digital record of every scan event for regulatory compliance
- **Shift-based Monitoring** — Track compliance patterns across different shifts

---

## 3. System Architecture

### High-Level Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│                        PHYSICAL LAYER                                │
│                                                                      │
│   ┌─────────────┐         ┌──────────────────────┐                   │
│   │  RFID Card  │ ──SPI──▶│  ESP32 WROOM         │                   │
│   │  (Mifare)   │         │  ┌─────────────────┐  │                   │
│   └─────────────┘         │  │ RC522 RFID Reader│  │                   │
│                           │  │ SH1106 OLED      │  │                   │
│                           │  │ Buzzer (GPIO4)   │  │                   │
│                           │  └─────────────────┘  │                   │
│                           └──────────┬───────────┘                   │
│                                      │ Wi-Fi (HTTP)                  │
├──────────────────────────────────────┼───────────────────────────────┤
│                        SOFTWARE LAYER│                               │
│                                      ▼                               │
│                           ┌──────────────────┐                       │
│                           │  Python Script    │                       │
│                           │  (Laptop/Server)  │                       │
│                           │  ┌──────────────┐ │                       │
│                           │  │ YOLOv8 AI    │ │                       │
│                           │  │ OpenCV       │ │                       │
│                           │  │ Webcam       │ │                       │
│                           │  └──────────────┘ │                       │
│                           └────────┬─────────┘                       │
│                                    │                                  │
│                                    ▼                                  │
│                           ┌──────────────────┐                       │
│                           │  SQLite Database  │                       │
│                           │  (ppe_monitor.db) │                       │
│                           └────────┬─────────┘                       │
│                                    │                                  │
│                                    ▼                                  │
│                           ┌──────────────────┐                       │
│                           │  Streamlit        │                       │
│                           │  Dashboard        │                       │
│                           │  (localhost:8501)  │                       │
│                           └──────────────────┘                       │
└──────────────────────────────────────────────────────────────────────┘
```

### Communication Flow

```
ESP32  ◄────────── Wi-Fi (HTTP REST API) ──────────►  Laptop (Python)
  │                                                        │
  │  GET /scan          → Python polls for new RFID scans  │
  │  POST /auth_result  ← Python sends auth decision       │
  │  POST /ppe_result   ← Python sends AI detection result │
  │                                                        │
  ▼                                                        ▼
OLED Display                                          SQLite Database
Buzzer Alerts                                         Streamlit Dashboard
```

### Three-Tier Architecture
| Tier | Component | Role |
|------|-----------|------|
| **Edge Layer** | ESP32 + RFID + OLED + Buzzer | Physical interaction with worker — scan, display, alert |
| **Processing Layer** | Python + YOLOv8 + OpenCV | AI inference, authorization logic, database logging |
| **Presentation Layer** | Streamlit Dashboard | Visual analytics, worker management, reports |

---

## 4. General Flow (End-to-End)

### Step-by-Step Workflow

```
  ① Worker taps RFID card on the RC522 reader
                    │
                    ▼
  ② ESP32 reads the UID, increments scan counter,
     sets access = "WAITING", shows "CHECKING..." on OLED
                    │
                    ▼
  ③ Python script (polling GET /scan every 1s) detects
     a new scan with access == "WAITING"
                    │
                    ▼
  ④ Python queries SQLite workers table:
     Is this UID registered AND active?
        │                       │
     YES (AUTHORIZED)        NO (DENIED)
        │                       │
        ▼                       ▼
  ⑤a Python sends POST       ⑤b Python sends POST
     /auth_result with           /auth_result with
     authorized=true             authorized=false
     + worker_name               │
        │                        ▼
        │                   ESP32 shows "ACCESS DENIED"
        │                   Buzzer: 3× long beeps
        │                   Scan logged to DB as DENIED
        │                   ── END ──
        ▼
  ⑥ ESP32 shows "AUTHORIZED" + worker name on OLED
     Buzzer: 2× short beeps (access granted)
                    │
                    ▼
  ⑦ 5-second positioning countdown
     "Stand in front of the camera"
     (Camera preview shows countdown overlay)
                    │
                    ▼
  ⑧ AI Detection begins — 5-frame majority voting:
     • Capture 5 fresh frames from webcam
     • Run YOLOv8 helmet detection on EACH frame
     • Run Haar cascade face detection on EACH frame
     • Count votes: helmet_on vs helmet_off vs no_person
     • Majority result wins
                    │
                    ▼
  ⑨ Result sent to ESP32 via POST /ppe_result
     + Result logged to SQLite database
                    │
         ┌─────────┼──────────┐
         ▼         ▼          ▼
     HELMET ON  HELMET OFF  NO PERSON
     OLED: OK   OLED: !     OLED: STAND IN VIEW
     Buzz: 1×   Buzz: 4×    (retry up to 2 more times)
     2s long    rapid beeps
```

### Key Design Decisions
- **Polling-based architecture** — Python polls ESP32 every 1 second (simple, reliable, no WebSocket complexity)
- **Dynamic authorization** — No hardcoded UIDs on ESP32; SQLite is the single source of truth
- **Majority voting** — 5-frame voting reduces single-frame false positives/negatives
- **No-person retries** — System gives the worker 2 extra chances (with 3-second gaps) to reposition
- **Fail-closed security** — If the database is unreachable, access is **denied** (safe default)

---

## 🗣️ Suggested Talking Points

> - "Our system bridges the gap between **physical safety enforcement** and **digital compliance monitoring**."
> - "The architecture is **modular** — the ESP32 edge device, the AI processing, and the dashboard are all independent components communicating via HTTP."
> - "Authorization is **dynamic and centralized** — adding or removing a worker takes effect immediately without touching the ESP32 firmware."
> - "Now I'll hand it over to **Vedant**, who will walk you through the specific hardware components, sensors, and technologies we used."

---

## 📌 Quick Reference — Numbers to Remember

| Metric | Value |
|--------|-------|
| Total automated tests | 316 |
| AI model | YOLOv8 (200 epochs, custom hardhat dataset) |
| Voting frames | 5 per detection |
| No-person retries | 2 (with 3s gap) |
| Positioning delay | 5 seconds |
| ESP32 poll interval | 1 second |
| Dashboard pages | 5 (Overview, Scan History, Violations, Workers, Reports) |
| Database tables | 2 (workers, ppe_scans) |
