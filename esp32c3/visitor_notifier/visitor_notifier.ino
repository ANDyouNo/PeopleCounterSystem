/*
 * People Counter — Visitor Notifier for ESP32-C3
 *
 * Pins (ESP32-C3):
 *   GPIO5  — TFM-51 buzzer
 *   GPIO4  — battery via a 100 kOhm + 100 kOhm divider
 *   GPIO7  — data input of a 3-pixel WS2812/NeoPixel strip
 *
 * LED #1: battery level (colour scale; blinking below 20 %)
 * LED #2: connection with PC software (blue / blinking red on loss)
 * LED #3: people in room (green / off)
 *
 * UDP protocol:
 *   ESP -> broadcast:4215  PCOUNTER_NOTIFIER:<battery_mV>
 *   PC  -> ESP:4214       KA                 (heartbeat)
 *                         STATE:<0|1>:<0|1>  (people, play visitor signal)
 *
 * Install the Adafruit NeoPixel library in Arduino IDE / PlatformIO.
 */

#include <WiFi.h>
#include <WiFiUdp.h>
#include <Adafruit_NeoPixel.h>
#include <esp_arduino_version.h>

// ── Set your Wi-Fi credentials ────────────────────────────────
const char* WIFI_SSID = "Honor 8A";
const char* WIFI_PASSWORD = "qwerty123";

// ── Hardware ──────────────────────────────────────────────────
#define BUZZER_PIN 5
#define BATTERY_PIN 4
#define LED_PIN 7
#define LED_COUNT 3
const uint8_t LED_BRIGHTNESS = 32;  // 0…255 NeoPixel range

// 100 kOhm + 100 kOhm divider means battery voltage is twice ADC voltage.
// Calibrate these two values for the actual single-cell Li-ion/LiPo battery.
const uint16_t BATTERY_EMPTY_MV = 3000;
const uint16_t BATTERY_FULL_MV = 4200;

// ── Network ───────────────────────────────────────────────────
const uint16_t CMD_PORT = 4214;
const uint16_t ANNOUNCE_PORT = 4215;
const char* ANNOUNCE_PREFIX = "PCOUNTER_NOTIFIER";
const unsigned long ANNOUNCE_INTERVAL_MS = 5000;
const unsigned long PC_TIMEOUT_MS = 5000;
const unsigned long CONNECTION_ALERT_INTERVAL_MS = 3000;
const unsigned long BATTERY_LOW_ALERT_INTERVAL_MS = 10UL * 60UL * 1000UL;
const unsigned long BATTERY_CRITICAL_ALERT_INTERVAL_MS = 60UL * 1000UL;
const unsigned long BATTERY_BLINK_INTERVAL_MS = 550;
const unsigned long WIFI_CONNECT_TIMEOUT_MS = 30000;
const unsigned long WIFI_RETRY_PAUSE_MS = 15000;

WiFiUDP udp;
Adafruit_NeoPixel pixels(LED_COUNT, LED_PIN, NEO_GRB + NEO_KHZ800);

bool peoplePresent = false;
bool pcConnected = false;
bool hasHeartbeat = false;
bool lowBattery = false;
bool connectionBlinkOn = false;
bool batteryBlinkOn = true;
// Wi-Fi event handlers run in the Wi-Fi task. They only set these atomic
// flags; WiFi.setSleep() itself is called later from the Arduino loop task.
volatile bool wifiSleepChangePending = false;
volatile bool wifiSleepDesiredState = false;
unsigned long lastAnnounce = 0;
unsigned long lastBatteryRead = 0;
unsigned long lastHeartbeat = 0;
unsigned long lastConnectionAlert = 0;
unsigned long lastBatteryAlert = 0;
unsigned long lastConnectionBlink = 0;
unsigned long lastBatteryBlink = 0;

// Non-blocking buzzer pattern. 0 in a pattern means silence.
const uint16_t VISITOR_PATTERN[] = {4100, 0, 4100, 0, 4100};
const uint16_t LOST_CONNECTION_PATTERN[] = {700, 0, 700};
const uint16_t LOW_BATTERY_PATTERN[] = {1200, 0, 1200, 0, 1200};
const uint16_t STARTUP_PATTERN[] = {1047, 0, 1319, 1568, 0, 2093};
const uint16_t BEEP_ON_MS = 145;
const uint16_t BEEP_OFF_MS = 95;
const uint16_t* activePattern = nullptr;
uint8_t activePatternLength = 0;
uint8_t patternIndex = 0;
unsigned long patternStepStarted = 0;
uint16_t batteryMv = 0;
uint8_t batteryPercent = 0;

void setBuzzerTone(uint16_t frequency) {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcWriteTone(BUZZER_PIN, frequency);
#else
  ledcWriteTone(0, frequency);
#endif
}

bool startPattern(const uint16_t* pattern, uint8_t length, bool interrupt = false) {
  // Visitor detection must not be hidden by a concurrent service alert.
  if (activePattern != nullptr && !interrupt) return false;
  activePattern = pattern;
  activePatternLength = length;
  patternIndex = 0;
  patternStepStarted = millis();
  setBuzzerTone(activePattern[0]);
  return true;
}

void tickBuzzer() {
  if (activePattern == nullptr) return;
  const bool sounding = activePattern[patternIndex] != 0;
  const unsigned long duration = sounding ? BEEP_ON_MS : BEEP_OFF_MS;
  if (millis() - patternStepStarted < duration) return;

  patternStepStarted = millis();
  ++patternIndex;
  if (patternIndex >= activePatternLength) {
    setBuzzerTone(0);
    activePattern = nullptr;
    return;
  }
  setBuzzerTone(activePattern[patternIndex]);
}

uint16_t readBatteryMv() {
  // ESP32's calibrated ADC conversion gives a more useful result than raw ADC.
  // Average several readings because the divider has a high impedance.
  uint32_t adcMvSum = 0;
  for (uint8_t i = 0; i < 8; ++i) {
    adcMvSum += analogReadMilliVolts(BATTERY_PIN);
    delay(2);
  }
  return static_cast<uint16_t>((adcMvSum / 8) * 2);
}

uint8_t calculateBatteryPercent(uint16_t millivolts) {
  if (millivolts <= BATTERY_EMPTY_MV) return 0;
  if (millivolts >= BATTERY_FULL_MV) return 100;
  return static_cast<uint8_t>(
    (static_cast<uint32_t>(millivolts - BATTERY_EMPTY_MV) * 100) /
    (BATTERY_FULL_MV - BATTERY_EMPTY_MV)
  );
}

void refreshBattery() {
  batteryMv = readBatteryMv();
  batteryPercent = calculateBatteryPercent(batteryMv);
  lowBattery = batteryPercent < 20;
  if (!lowBattery) batteryBlinkOn = true;
}

uint32_t batteryColor() {
  // 100–90 green, 89–75 light green, 74–50 yellow,
  // 49–25 orange, 24–20 red-orange, 19–10 blinking red-orange,
  // 9–0 blinking red.
  if (batteryPercent >= 90) return pixels.Color(0, 220, 0);
  if (batteryPercent >= 75) return pixels.Color(120, 220, 0);
  if (batteryPercent >= 50) return pixels.Color(255, 180, 0);
  if (batteryPercent >= 25) return pixels.Color(255, 75, 0);
  if (batteryPercent >= 20) return pixels.Color(255, 25, 0);
  if (!batteryBlinkOn) return 0;
  if (batteryPercent >= 10) return pixels.Color(255, 35, 0);
  return pixels.Color(255, 0, 0);
}

void updateLeds() {
  const uint32_t pcColor = pcConnected
    ? pixels.Color(0, 90, 255)
    : (connectionBlinkOn ? pixels.Color(255, 0, 0) : 0);
  const uint32_t peopleColor = peoplePresent ? pixels.Color(0, 220, 0) : 0;
  pixels.setPixelColor(0, batteryColor());
  pixels.setPixelColor(1, pcColor);
  pixels.setPixelColor(2, peopleColor);
  pixels.show();
}

void sendAnnounce(uint16_t batteryMv) {
  IPAddress broadcast = WiFi.localIP();
  broadcast[3] = 255;
  udp.beginPacket(broadcast, ANNOUNCE_PORT);
  udp.printf("%s:%u", ANNOUNCE_PREFIX, batteryMv);
  udp.endPacket();
}

void processCommand(const String& command) {
  if (command == "KA") {
    lastHeartbeat = millis();
    hasHeartbeat = true;
    return;
  }

  if (!command.startsWith("STATE:")) return;
  const int secondColon = command.indexOf(':', 6);
  if (secondColon < 0) return;
  const bool occupied = command.substring(6, secondColon).toInt() != 0;
  const bool playVisitorSignal = command.substring(secondColon + 1).toInt() != 0;

  peoplePresent = occupied;
  lastHeartbeat = millis();
  hasHeartbeat = true;
  if (playVisitorSignal && occupied) {
    startPattern(VISITOR_PATTERN, sizeof(VISITOR_PATTERN) / sizeof(VISITOR_PATTERN[0]), true);
  }
}

void onWiFiEvent(WiFiEvent_t event, WiFiEventInfo_t info) {
  switch (event) {
    case ARDUINO_EVENT_WIFI_STA_CONNECTED:
      Serial.println("[WiFi] Connected to access point, requesting IP...");
      break;
    case ARDUINO_EVENT_WIFI_STA_GOT_IP:
      Serial.printf("[WiFi] IP address: %s\n", WiFi.localIP().toString().c_str());
      // Handshake and DHCP succeeded: enable modem sleep in loop().
      wifiSleepDesiredState = true;
      wifiSleepChangePending = true;
      break;
    case ARDUINO_EVENT_WIFI_STA_DISCONNECTED:
      Serial.printf("[WiFi] Disconnected, reason: %d\n", info.wifi_sta_disconnected.reason);
      // Keep the current power-save setting. Changing it here, or shortly
      // afterwards, may race with the driver's automatic reconnect attempt.
      break;
    default:
      break;
  }
}

void tickConnectingUi() {
  // Blink the PC connection LED while Wi-Fi is unavailable, without stopping
  // the startup sound or battery indication.
  connectionBlinkOn = !connectionBlinkOn;
  updateLeds();
  for (uint8_t i = 0; i < 35; ++i) {
    tickBuzzer();
    delay(10);
  }
}

void connectToWiFi() {
  uint32_t attempt = 0;
  while (WiFi.status() != WL_CONNECTED) {
    ++attempt;
    Serial.printf("[WiFi] Connection attempt %lu to \"%s\"\n", attempt, WIFI_SSID);

    WiFi.mode(WIFI_OFF);
    delay(300);
    WiFi.mode(WIFI_STA);

    bool sleepOk = WiFi.setSleep(false);      // теперь драйвер уже поднят — применится реально
    Serial.printf("[WiFi] setSleep(false) -> %s\n", sleepOk ? "ok" : "FAILED");

    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    const unsigned long startedAt = millis();
    while (WiFi.status() != WL_CONNECTED &&
           millis() - startedAt < WIFI_CONNECT_TIMEOUT_MS) {
      tickConnectingUi();
    }

    if (WiFi.status() == WL_CONNECTED) return;

    Serial.println("[WiFi] Attempt timed out; retrying with a fresh station...");
    const unsigned long retryStartedAt = millis();
    while (millis() - retryStartedAt < WIFI_RETRY_PAUSE_MS) {
      tickConnectingUi();
    }
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(BATTERY_PIN, INPUT);
  analogReadResolution(12);
  analogSetPinAttenuation(BATTERY_PIN, ADC_11db);

#if ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcAttach(BUZZER_PIN, 2000, 8);
#else
  ledcSetup(0, 2000, 8);
  ledcAttachPin(BUZZER_PIN, 0);
#endif
  setBuzzerTone(0);

  pixels.begin();
  pixels.setBrightness(LED_BRIGHTNESS);
  pixels.clear();
  pixels.show();

  refreshBattery();
  lastBatteryRead = millis();
  startPattern(STARTUP_PATTERN, sizeof(STARTUP_PATTERN) / sizeof(STARTUP_PATTERN[0]));

  WiFi.onEvent(onWiFiEvent);
  connectToWiFi();
  // Auto-reconnect is enabled only after the initial connection is complete,
  // so it cannot race with the manual startup retry sequence above.
  WiFi.setAutoReconnect(true);

  udp.begin(CMD_PORT);
  refreshBattery();
  lastBatteryRead = millis();
  if (lowBattery) {
    // First warning is immediate; interval afterwards depends on severity.
    const unsigned long interval = batteryPercent < 10
      ? BATTERY_CRITICAL_ALERT_INTERVAL_MS
      : BATTERY_LOW_ALERT_INTERVAL_MS;
    lastBatteryAlert = millis() - interval;
  }
  sendAnnounce(batteryMv);
  lastAnnounce = millis();
  updateLeds();
  Serial.printf("Visitor notifier ready, IP: %s, battery: %u mV\n",
                WiFi.localIP().toString().c_str(), batteryMv);
}

void loop() {
  // Must run outside onWiFiEvent(): the callback belongs to the Wi-Fi task.
  if (wifiSleepChangePending) {
    wifiSleepChangePending = false;
    const bool sleepOk = WiFi.setSleep(wifiSleepDesiredState);
    Serial.printf("[WiFi] setSleep(%s) -> %s\n",
                  wifiSleepDesiredState ? "true" : "false",
                  sleepOk ? "ok" : "FAILED");
  }

  int packetSize = udp.parsePacket();
  if (packetSize > 0) {
    char buffer[48] = {0};
    const int length = udp.read(buffer, sizeof(buffer) - 1);
    if (length > 0) {
      buffer[length] = '\0';
      String command(buffer);
      command.trim();
      processCommand(command);
    }
  }

  const unsigned long now = millis();
  if (now - lastBatteryRead >= ANNOUNCE_INTERVAL_MS) {
    lastBatteryRead = now;
    refreshBattery();
  }
  if (lowBattery && now - lastBatteryBlink >= BATTERY_BLINK_INTERVAL_MS) {
    lastBatteryBlink = now;
    batteryBlinkOn = !batteryBlinkOn;
  }

  if (now - lastAnnounce >= ANNOUNCE_INTERVAL_MS) {
    lastAnnounce = now;
    sendAnnounce(batteryMv);
  }

  const bool wasConnected = pcConnected;
  pcConnected = hasHeartbeat && now - lastHeartbeat < PC_TIMEOUT_MS;
  if (!pcConnected && now - lastConnectionBlink >= 450) {
    lastConnectionBlink = now;
    connectionBlinkOn = !connectionBlinkOn;
  }
  if (pcConnected) connectionBlinkOn = true;

  if (!pcConnected && (wasConnected || now - lastConnectionAlert >= CONNECTION_ALERT_INTERVAL_MS)) {
    lastConnectionAlert = now;
    startPattern(LOST_CONNECTION_PATTERN,
                 sizeof(LOST_CONNECTION_PATTERN) / sizeof(LOST_CONNECTION_PATTERN[0]));
  }
  const unsigned long batteryAlertInterval = batteryPercent < 10
    ? BATTERY_CRITICAL_ALERT_INTERVAL_MS
    : BATTERY_LOW_ALERT_INTERVAL_MS;
  if (lowBattery && now - lastBatteryAlert >= batteryAlertInterval) {
    if (startPattern(LOW_BATTERY_PATTERN,
                     sizeof(LOW_BATTERY_PATTERN) / sizeof(LOW_BATTERY_PATTERN[0]))) {
      lastBatteryAlert = now;
    }
  }

  updateLeds();
  tickBuzzer();
  delay(5);
}
