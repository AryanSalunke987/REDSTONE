
#include <WiFi.h>
#include <WebServer.h>
#include <SPI.h>
#include <MFRC522.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SH110X.h>

// 1. Wi-Fi
const char* ssid = "deeznutz";
const char* password = "jotarokujo";

// 2. Pins
#define RFID_SS 5
#define RFID_RST 22
#define RFID_SCK 18
#define RFID_MISO 19
#define RFID_MOSI 23
#define BUZZER_PIN 4
#define OLED_SDA 21
#define OLED_SCL 25
#define OLED_ADDRESS 0x3C
#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64

// 3. Hardware objects
MFRC522 rfid(RFID_SS, RFID_RST);
WebServer server(80);
Adafruit_SH1106G display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1);

// 4. Latest scan information
// NOTE: No hardcoded authorized UIDs — Python/SQLite is the authority.
String latestUID = "None";
String latestAccess = "WAITING";
String latestPPE = "PENDING";
String latestWorkerName = "";
bool scanned = false;
unsigned long scanCount = 0;

// 4a. Non-blocking buzzer state machine (for PPE alerts)
bool buzzerActive = false;
int buzzerBeepsLeft = 0;
unsigned long buzzerNextTime = 0;
bool buzzerIsOn = false;
unsigned int buzzerOnMs = 100;
unsigned int buzzerOffMs = 100;

// 4b. OLED auto-return timer
unsigned long oledReturnAt = 0;
bool oledReturnPending = false;

// 5. OLED display - full-height layout
void showScreen(const String& line1,
                const String& line2 = "",
                const String& line3 = "",
                const String& line4 = "") {
  display.clearDisplay();
  display.setTextColor(SH110X_WHITE);
  display.setTextSize(1);
  display.setTextWrap(false);

  // Header
  display.setCursor(0, 0);
  display.println(line1);
  display.drawLine(0, 11, 127, 11, SH110X_WHITE);

  // Three evenly spaced content rows
  if (line2 != "") {
    display.setCursor(0, 15);
    display.println(line2);
  }
  if (line3 != "") {
    display.setCursor(0, 31);
    display.println(line3);
  }
  if (line4 != "") {
    display.setCursor(0, 47);
    display.println(line4);
  }

  display.display();
}

void showReadyScreen() {
  showScreen(
    "PPE MONITORING",
    "SYSTEM: ONLINE",
    "RFID: READY",
    "SCAN YOUR RFID CARD"
  );
}

void showCheckingScreen(const String& uid) {
  showScreen(
    "PPE MONITORING",
    "RFID: CHECKING...",
    "UID:" + uid,
    "VERIFYING ACCESS"
  );
}

void showAuthorizedScreen(const String& nameOrUid) {
  showScreen(
    "PPE MONITORING",
    "RFID: AUTHORIZED",
    "WORKER:" + nameOrUid,
    "PPE: AI PENDING"
  );
}

void showDeniedScreen(const String& uid) {
  showScreen(
    "PPE MONITORING",
    "RFID: ACCESS DENIED",
    "UNKNOWN WORKER",
    "UID: " + uid
  );
}

// 5a. PPE result OLED screens
void showHelmetOnScreen(const String& nameOrUid) {
  showScreen(
    "PPE MONITORING",
    "RFID: AUTHORIZED",
    "WORKER:" + nameOrUid,
    "PPE: HELMET OK"
  );
}

void showHelmetOffScreen(const String& nameOrUid) {
  showScreen(
    "PPE MONITORING",
    "RFID: AUTHORIZED",
    "WORKER:" + nameOrUid,
    "PPE: NO HELMET !"
  );
}

void showNoPersonScreen(const String& nameOrUid) {
  showScreen(
    "PPE MONITORING",
    "RFID: AUTHORIZED",
    "WORKER:" + nameOrUid,
    "PPE: STAND IN VIEW"
  );
}

void showErrorScreen(const String& nameOrUid) {
  showScreen(
    "PPE MONITORING",
    "RFID: AUTHORIZED",
    "WORKER:" + nameOrUid,
    "PPE: VERIFY ERROR"
  );
}

// 6. Buzzer alerts
void accessGrantedBeep() {
  for (int i = 0; i < 2; i++) {
    tone(BUZZER_PIN, 2000);
    delay(200);
    noTone(BUZZER_PIN);
    delay(150);
  }
}

void accessDeniedBeep() {
  for (int i = 0; i < 3; i++) {
    tone(BUZZER_PIN, 2000);
    delay(500);
    noTone(BUZZER_PIN);
    delay(500);
  }
}

// 6a. Non-blocking PPE buzzer (keeps HTTP server responsive)
void startBuzzerPattern(int beeps, unsigned int onMs, unsigned int offMs) {
  buzzerBeepsLeft = beeps;
  buzzerOnMs = onMs;
  buzzerOffMs = offMs;
  buzzerActive = true;
  buzzerIsOn = true;
  tone(BUZZER_PIN, 2000);
  buzzerNextTime = millis() + onMs;
}

void updateBuzzer() {
  if (!buzzerActive) return;
  if (millis() < buzzerNextTime) return;

  if (buzzerIsOn) {
    noTone(BUZZER_PIN);
    buzzerIsOn = false;
    buzzerBeepsLeft--;
    if (buzzerBeepsLeft <= 0) {
      buzzerActive = false;
      return;
    }
    buzzerNextTime = millis() + buzzerOffMs;
  } else {
    tone(BUZZER_PIN, 2000);
    buzzerIsOn = true;
    buzzerNextTime = millis() + buzzerOnMs;
  }
}

// 6b. OLED auto-return to ready screen
void scheduleOLEDReturn(unsigned long delayMs) {
  oledReturnAt = millis() + delayMs;
  oledReturnPending = true;
}

void checkOLEDReturn() {
  if (!oledReturnPending) return;
  if (millis() >= oledReturnAt) {
    oledReturnPending = false;
    showReadyScreen();
  }
}

// 7. RFID functions
String getUIDString() {
  String uid = "";

  for (byte i = 0; i < rfid.uid.size; i++) {
    if (rfid.uid.uidByte[i] < 0x10) {
      uid += "0";
    }
    uid += String(rfid.uid.uidByte[i], HEX);
    if (i < rfid.uid.size - 1) {
      uid += " ";
    }
  }

  uid.toUpperCase();
  return uid;
}

void checkRFID() {
  if (!rfid.PICC_IsNewCardPresent()) return;
  if (!rfid.PICC_ReadCardSerial()) return;

  latestUID = getUIDString();
  scanned = true;
  scanCount++;
  // Authorization will be determined by Python — set to WAITING
  latestAccess = "WAITING";
  latestPPE = "PENDING";
  latestWorkerName = "";

  // Cancel any pending PPE buzzer/OLED from previous scan
  if (buzzerActive) {
    buzzerActive = false;
    noTone(BUZZER_PIN);
  }
  oledReturnPending = false;

  Serial.println();
  Serial.println("------------------------------");
  Serial.println("RFID scan: " + latestUID);
  Serial.println("Waiting for Python authorization...");

  // Show "checking" screen while Python decides
  showCheckingScreen(latestUID);

  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();

  Serial.println("------------------------------");
}

// 8. HTTP endpoints
void handleRoot() {
  server.send(
    200,
    "text/plain",
    "ESP32 PPE Monitoring System is online. "
    "Visit /scan for the latest scan."
  );
}

void handleScan() {
  String json = "{";

  json += "\"device\":\"ESP32 PPE Monitor\",";
  json += "\"scanned\":";
  json += scanned ? "true," : "false,";
  json += "\"uid\":\"" + latestUID + "\",";
  json += "\"access\":\"" + latestAccess + "\",";
  json += "\"ppe\":\"" + latestPPE + "\",";
  json += "\"count\":" + String(scanCount);

  json += "}";

  server.send(200, "application/json", json);
}

// 8a. Authorization result endpoint (receives auth decision from Python)
void handleAuthResult() {
  String body = server.arg("plain");

  // Parse scan_id (numeric value)
  int sidx = body.indexOf("\"scan_id\":");
  if (sidx < 0) {
    server.send(400, "application/json", "{\"error\":\"missing scan_id\"}");
    return;
  }
  unsigned long recvScanId = 0;
  int pos = sidx + 10;
  while (pos < (int)body.length() && body[pos] == ' ') pos++;
  while (pos < (int)body.length() && body[pos] >= '0' && body[pos] <= '9') {
    recvScanId = recvScanId * 10 + (body[pos] - '0');
    pos++;
  }

  // Parse authorized (boolean value)
  int aidx = body.indexOf("\"authorized\":");
  if (aidx < 0) {
    server.send(400, "application/json", "{\"error\":\"missing authorized\"}");
    return;
  }
  int apos = aidx + 13;
  while (apos < (int)body.length() && body[apos] == ' ') apos++;
  bool authorized = false;
  if (apos < (int)body.length() && body[apos] == 't') {
    authorized = true;
  }

  // Parse worker_name (optional string value)
  String workerName = "";
  int nidx = body.indexOf("\"worker_name\":\"");
  if (nidx >= 0) {
    int nStart = nidx + 15;
    int nEnd = body.indexOf("\"", nStart);
    if (nEnd > nStart) {
      workerName = body.substring(nStart, nEnd);
    }
  }

  // Reject stale results from a previous scan
  if (recvScanId != scanCount) {
    String resp = "{\"error\":\"stale scan_id\",\"current\":";
    resp += String(scanCount);
    resp += ",\"received\":";
    resp += String(recvScanId);
    resp += "}";
    server.send(409, "application/json", resp);
    Serial.println("Auth rejected: stale scan_id " + String(recvScanId));
    return;
  }

  if (authorized) {
    latestAccess = "AUTHORIZED";
    latestWorkerName = workerName;
    Serial.println("Auth result: AUTHORIZED — " + workerName);

    String displayName = workerName.length() > 0 ? workerName : latestUID;
    showAuthorizedScreen(displayName);
    accessGrantedBeep();
  } else {
    latestAccess = "DENIED";
    latestWorkerName = workerName;  // May be set for inactive workers
    Serial.println("Auth result: DENIED — UID: " + latestUID);

    showDeniedScreen(latestUID);
    accessDeniedBeep();
    scheduleOLEDReturn(8000);  // Return to ready screen in 8s
  }

  String resp = "{\"ok\":true,\"authorized\":";
  resp += authorized ? "true" : "false";
  resp += ",\"scan_id\":";
  resp += String(scanCount);
  resp += "}";
  server.send(200, "application/json", resp);
}

// 8b. PPE result endpoint (receives AI detection result from laptop)
void handlePPEResult() {
  String body = server.arg("plain");

  // Parse scan_id (numeric value)
  int sidx = body.indexOf("\"scan_id\":");
  if (sidx < 0) {
    server.send(400, "application/json", "{\"error\":\"missing scan_id\"}");
    return;
  }
  unsigned long recvScanId = 0;
  int pos = sidx + 10;
  while (pos < (int)body.length() && body[pos] == ' ') pos++;
  while (pos < (int)body.length() && body[pos] >= '0' && body[pos] <= '9') {
    recvScanId = recvScanId * 10 + (body[pos] - '0');
    pos++;
  }

  // Parse status (string value — skip optional whitespace after colon)
  int stidx = body.indexOf("\"status\":");
  if (stidx < 0) {
    server.send(400, "application/json", "{\"error\":\"missing status\"}");
    return;
  }
  int stPos = stidx + 9;  // length of "status":
  while (stPos < (int)body.length() && body[stPos] == ' ') stPos++;
  if (stPos >= (int)body.length() || body[stPos] != '"') {
    server.send(400, "application/json", "{\"error\":\"missing status\"}");
    return;
  }
  int stStart = stPos + 1;  // skip the opening quote
  int stEnd = body.indexOf("\"", stStart);
  if (stEnd < 0) {
    server.send(400, "application/json", "{\"error\":\"malformed status\"}");
    return;
  }
  String status = body.substring(stStart, stEnd);

  // Parse "final" boolean (defaults to true if absent for backward compat)
  bool isFinal = true;
  int fidx = body.indexOf("\"final\":");
  if (fidx >= 0) {
    int fpos = fidx + 8;  // length of "final":
    while (fpos < (int)body.length() && body[fpos] == ' ') fpos++;
    if (fpos < (int)body.length() && body[fpos] == 'f') {
      isFinal = false;  // "final": false
    }
  }

  // Reject stale results from a previous scan
  if (recvScanId != scanCount) {
    String resp = "{\"error\":\"stale scan_id\",\"current\":";
    resp += String(scanCount);
    resp += ",\"received\":";
    resp += String(recvScanId);
    resp += "}";
    server.send(409, "application/json", resp);
    Serial.println("PPE rejected: stale scan_id " + String(recvScanId));
    return;
  }

  // Validate status value
  if (status != "helmet_on" && status != "helmet_off" &&
      status != "no_person" && status != "verification_error") {
    server.send(400, "application/json", "{\"error\":\"invalid status\"}");
    return;
  }

  // Apply PPE result — update OLED and trigger buzzer
  latestPPE = status;
  Serial.println("PPE result: " + status + " (scan #" + String(scanCount)
                 + ", final=" + (isFinal ? "true" : "false") + ")");

  // Use worker name for display if available, otherwise UID
  String displayName = latestWorkerName.length() > 0 ? latestWorkerName : latestUID;

  if (status == "helmet_on") {
    showHelmetOnScreen(displayName);
    // One continuous 2-second buzz (single beep, 2000ms on)
    startBuzzerPattern(1, 2000, 0);
  } else if (status == "helmet_off") {
    showHelmetOffScreen(displayName);
    // Four rapid beeps (existing pattern)
    startBuzzerPattern(4, 100, 100);
  } else if (status == "no_person") {
    showNoPersonScreen(displayName);
    // Only play buzzer on the FINAL no_person (after all retries)
    if (isFinal) {
      // Two gentle 150ms beeps with 200ms gap
      startBuzzerPattern(2, 150, 200);
    }
  } else {
    // verification_error — no buzzer
    showErrorScreen(displayName);
  }

  scheduleOLEDReturn(8000);  // Return to ready screen in 8s

  String resp = "{\"ok\":true,\"status\":\"";
  resp += status;
  resp += "\",\"scan_id\":";
  resp += String(scanCount);
  resp += ",\"final\":";
  resp += isFinal ? "true" : "false";
  resp += "}";
  server.send(200, "application/json", resp);
}

// 9. Setup
void setup() {
  Serial.begin(115200);
  delay(500);

  // Buzzer
  pinMode(BUZZER_PIN, OUTPUT);
  noTone(BUZZER_PIN);

  // OLED
  Wire.begin(OLED_SDA, OLED_SCL);

  if (!display.begin(OLED_ADDRESS, true)) {
    Serial.println("OLED initialization failed!");
    while (true) {
      delay(1000);
    }
  }

  showScreen("PPE MONITORING", "INITIALIZING...");

  // RFID SPI
  SPI.begin(RFID_SCK, RFID_MISO, RFID_MOSI, RFID_SS);
  rfid.PCD_Init();
  delay(100);
  Serial.println("RFID initialized.");

  // Wi-Fi
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);

  showScreen("PPE MONITORING", "CONNECTING TO WIFI");

  Serial.print("Connecting to Wi-Fi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println();
  Serial.println("Wi-Fi connected!");
  Serial.print("ESP32 IP: ");
  Serial.println(WiFi.localIP());

  // HTTP server
  server.on("/", handleRoot);
  server.on("/scan", handleScan);
  server.on("/auth_result", HTTP_POST, handleAuthResult);
  server.on("/ppe_result", HTTP_POST, handlePPEResult);
  server.begin();

  Serial.println("HTTP server started.");
  Serial.println("Authorization: Dynamic (Python/SQLite)");
  showReadyScreen();
}

// 10. Main loop
void loop() {
  server.handleClient();
  checkRFID();
  updateBuzzer();
  checkOLEDReturn();
}