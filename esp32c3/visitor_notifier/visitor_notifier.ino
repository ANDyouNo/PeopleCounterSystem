/*
 * People Counter — Visitor Notifier for ESP32-C3
 *
 * Pins (ESP32-C3):
 *   GPIO5  — TFM-51 buzzer
 *   GPIO4  — battery via a 100 kOhm + 100 kOhm divider
 *   GPIO7  — data input of a 3-pixel WS2812/NeoPixel strip
 *
 * LED #1: battery (green / red on low charge)
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
const char* WIFI_SSID = "YOUR_SSID";
const char* WIFI_PASSWORD = "YOUR_PASSWORD";

// ── Hardware ──────────────────────────────────────────────────
#define BUZZER_PIN 5
#define BATTERY_PIN 4
#define LED_PIN 7
#define LED_COUNT 3
const uint8_t LED_BRIGHTNESS = 128;  // 50 % of the 0…255 NeoPixel range

// 100 kOhm + 100 kOhm divider means battery voltage is twice ADC voltage.
// LOW_BATTERY_MV is intended for a single-cell Li-ion/LiPo battery.
const uint16_t LOW_BATTERY_MV = 3500;

// ── Network ───────────────────────────────────────────────────
const uint16_t CMD_PORT = 4214;
const uint16_t ANNOUNCE_PORT = 4215;
const char* ANNOUNCE_PREFIX = "PCOUNTER_NOTIFIER";
const unsigned long ANNOUNCE_INTERVAL_MS = 5000;
const unsigned long PC_TIMEOUT_MS = 5000;
const unsigned long CONNECTION_ALERT_INTERVAL_MS = 3000;
const unsigned long BATTERY_ALERT_INTERVAL_MS = 10UL * 60UL * 1000UL;

WiFiUDP udp;
Adafruit_NeoPixel pixels(LED_COUNT, LED_PIN, NEO_GRB + NEO_KHZ800);

bool peoplePresent = false;
bool pcConnected = false;
bool hasHeartbeat = false;
bool lowBattery = false;
bool connectionBlinkOn = false;
unsigned long lastAnnounce = 0;
unsigned long lastBatteryRead = 0;
unsigned long lastHeartbeat = 0;
unsigned long lastConnectionAlert = 0;
unsigned long lastBatteryAlert = 0;
unsigned long lastConnectionBlink = 0;

// Non-blocking buzzer pattern. 0 in a pattern means silence.
const uint16_t VISITOR_PATTERN[] = {1900, 0, 2400, 0, 2900};
const uint16_t LOST_CONNECTION_PATTERN[] = {700, 0, 700};
const uint16_t LOW_BATTERY_PATTERN[] = {1200, 0, 1200, 0, 1200};
const uint16_t BEEP_ON_MS = 145;
const uint16_t BEEP_OFF_MS = 95;
const uint16_t* activePattern = nullptr;
uint8_t activePatternLength = 0;
uint8_t patternIndex = 0;
unsigned long patternStepStarted = 0;
uint16_t batteryMv = 0;

void setBuzzerTone(uint16_t frequency) {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcWriteTone(BUZZER_PIN, frequency);
#else
  ledcWriteTone(0, frequency);
#endif
}

void startPattern(const uint16_t* pattern, uint8_t length, bool interrupt = false) {
  // Visitor detection must not be hidden by a concurrent service alert.
  if (activePattern != nullptr && !interrupt) return;
  activePattern = pattern;
  activePatternLength = length;
  patternIndex = 0;
  patternStepStarted = millis();
  setBuzzerTone(activePattern[0]);
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

void updateLeds() {
  const uint32_t batteryColor = lowBattery ? pixels.Color(255, 0, 0) : pixels.Color(0, 180, 0);
  const uint32_t pcColor = pcConnected
    ? pixels.Color(0, 90, 255)
    : (connectionBlinkOn ? pixels.Color(255, 0, 0) : 0);
  const uint32_t peopleColor = peoplePresent ? pixels.Color(0, 220, 0) : 0;
  pixels.setPixelColor(0, batteryColor);
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

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    // Blinking red shows that Wi-Fi is not ready for a PC heartbeat yet.
    connectionBlinkOn = !connectionBlinkOn;
    updateLeds();
    delay(350);
  }

  udp.begin(CMD_PORT);
  batteryMv = readBatteryMv();
  lastBatteryRead = millis();
  lowBattery = batteryMv < LOW_BATTERY_MV;
  if (lowBattery) {
    // First warning is immediate; subsequent ones are exactly ten minutes apart.
    lastBatteryAlert = millis() - BATTERY_ALERT_INTERVAL_MS;
  }
  sendAnnounce(batteryMv);
  lastAnnounce = millis();
  updateLeds();
  Serial.printf("Visitor notifier ready, IP: %s, battery: %u mV\n",
                WiFi.localIP().toString().c_str(), batteryMv);
}

void loop() {
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
    batteryMv = readBatteryMv();
    lowBattery = batteryMv < LOW_BATTERY_MV;
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
  if (lowBattery && now - lastBatteryAlert >= BATTERY_ALERT_INTERVAL_MS) {
    lastBatteryAlert = now;
    startPattern(LOW_BATTERY_PATTERN,
                 sizeof(LOW_BATTERY_PATTERN) / sizeof(LOW_BATTERY_PATTERN[0]));
  }

  updateLeds();
  tickBuzzer();
  delay(5);
}
