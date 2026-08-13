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
#include <esp_wifi.h>  // wifi_ps_type_t (WIFI_PS_NONE / WIFI_PS_MIN_MODEM / WIFI_PS_MAX_MODEM)

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
const unsigned long PC_TIMEOUT_MS = 6000;
const unsigned long CONNECTION_ALERT_INTERVAL_MS = 3000;
const unsigned long BATTERY_LOW_ALERT_INTERVAL_MS = 10UL * 60UL * 1000UL;
const unsigned long BATTERY_CRITICAL_ALERT_INTERVAL_MS = 60UL * 1000UL;
const unsigned long BATTERY_BLINK_INTERVAL_MS = 550;

// ── Wi-Fi connection strategy ────────────────────────────────────
// Энергопотребление сейчас не приоритет — вся логика ниже заточена
// исключительно под то, чтобы соединение устанавливалось при любых
// разумных условиях, даже ценой более активного радио.
const unsigned long WIFI_CONNECT_TIMEOUT_MS = 20000;   // ждать один WiFi.begin()
const unsigned long WIFI_RETRY_BASE_DELAY_MS = 3000;   // пауза перед 2-й попыткой
const unsigned long WIFI_RETRY_MAX_DELAY_MS = 30000;   // потолок экспоненциального роста паузы
const uint32_t WIFI_HARD_RESET_AFTER_FAILURES = 3;     // после N неудач подряд — сброс креденшлов в NVS
const uint32_t WIFI_FULL_REBOOT_AFTER_FAILURES = 8;    // после M неудач подряд — полный перезапуск чипа
// Известный аппаратный дефект дешёвых плат ESP32-C3 SuperMini: бортовой
// стабилизатор питания не держит пиковый ток (~500 мА) при передаче на
// полной мощности (19.5 дБм по умолчанию), и в момент отправки
// auth-фрейма происходит просадка питания — внешне это неотличимо от
// AUTH_EXPIRE в цикле, причём одинаково на любой точке доступа, потому что
// причина не в сети, а в самой плате. Официальный обходной путь (issue
// espressif/arduino-esp32 #6767 и другие) — снизить TX-мощность.

// const wifi_power_t WIFI_TX_POWER = WIFI_POWER_MINUS_1dBm; // -1 дБм — минимум
// const wifi_power_t WIFI_TX_POWER = WIFI_POWER_2dBm;       //  2 дБм
// const wifi_power_t WIFI_TX_POWER = WIFI_POWER_5dBm;       //  5 дБм
// const wifi_power_t WIFI_TX_POWER = WIFI_POWER_7dBm;       //  7 дБм
const wifi_power_t WIFI_TX_POWER = WIFI_POWER_8_5dBm;     //  8.5 дБм — то, что стоит сейчас
// const wifi_power_t WIFI_TX_POWER = WIFI_POWER_11dBm;      // 11 дБм
// const wifi_power_t WIFI_TX_POWER = WIFI_POWER_13dBm;      // 13 дБм
// const wifi_power_t WIFI_TX_POWER = WIFI_POWER_15dBm;      // 15 дБм
// const wifi_power_t WIFI_TX_POWER = WIFI_POWER_17dBm;      // 17 дБм
// const wifi_power_t WIFI_TX_POWER = WIFI_POWER_18_5dBm;    // 18.5 дБм
// const wifi_power_t WIFI_TX_POWER = WIFI_POWER_19dBm;      // 19 дБм
// const wifi_power_t WIFI_TX_POWER = WIFI_POWER_19_5dBm;    // 19.5 дБм — максимум (дефолт платы)

WiFiUDP udp;
Adafruit_NeoPixel pixels(LED_COUNT, LED_PIN, NEO_GRB + NEO_KHZ800);

bool peoplePresent = false;
bool pcConnected = false;
bool hasHeartbeat = false;
bool lowBattery = false;
bool connectionBlinkOn = false;
bool batteryBlinkOn = true;
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

IPAddress computeBroadcastAddress() {
  const IPAddress ip = WiFi.localIP();
  IPAddress mask = WiFi.subnetMask();
  // Защита на случай, если маска ещё не готова (0.0.0.0) — тогда откатываемся
  // к прежнему предположению "/24", которое верно для типичной раздачи с
  // телефона (обычно 192.168.x.0/24).
  if (mask[0] == 0 && mask[1] == 0 && mask[2] == 0 && mask[3] == 0) {
    mask = IPAddress(255, 255, 255, 0);
  }
  IPAddress broadcast;
  for (uint8_t i = 0; i < 4; ++i) {
    broadcast[i] = ip[i] | (~mask[i] & 0xFF);
  }
  return broadcast;
}

void sendAnnounce(uint16_t batteryMv) {
  udp.beginPacket(computeBroadcastAddress(), ANNOUNCE_PORT);
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

// Коды из esp_wifi_types.h — печатаем текстом, чтобы не гадать по цифрам.
const char* wifiReasonToString(uint8_t reason) {
  switch (reason) {
    case 1: return "UNSPECIFIED";
    case 2: return "AUTH_EXPIRE";
    case 3: return "AUTH_LEAVE";
    case 4: return "ASSOC_EXPIRE";
    case 5: return "ASSOC_TOOMANY";
    case 6: return "NOT_AUTHED";
    case 7: return "NOT_ASSOCED";
    case 8: return "ASSOC_LEAVE";
    case 9: return "ASSOC_NOT_AUTHED";
    case 15: return "4WAY_HANDSHAKE_TIMEOUT";
    case 16: return "GROUP_KEY_UPDATE_TIMEOUT";
    case 23: return "802_1X_AUTH_FAILED";
    case 200: return "BEACON_TIMEOUT";
    case 201: return "NO_AP_FOUND";
    case 202: return "AUTH_FAIL";
    case 203: return "ASSOC_FAIL";
    case 204: return "HANDSHAKE_TIMEOUT";
    case 205: return "CONNECTION_FAIL";
    default: return "?";
  }
}

void onWiFiEvent(WiFiEvent_t event, WiFiEventInfo_t info) {
  switch (event) {
    case ARDUINO_EVENT_WIFI_STA_CONNECTED:
      Serial.println("[WiFi] Connected to access point, requesting IP...");
      break;
    case ARDUINO_EVENT_WIFI_STA_GOT_IP:
      Serial.printf("[WiFi] IP address: %s\n", WiFi.localIP().toString().c_str());
      break;
    case ARDUINO_EVENT_WIFI_STA_DISCONNECTED:
      Serial.printf("[WiFi] Disconnected, reason: %d (%s)\n",
                     info.wifi_sta_disconnected.reason,
                     wifiReasonToString(info.wifi_sta_disconnected.reason));
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

void relaxCountryChannelLimits() {
  // По умолчанию некоторые версии ядра поднимают Wi-Fi в регуляторном
  // домене "world safe", который урезает разрешённые каналы до 1–11. Если
  // роутер/точка доступа сидит на 12 или 13 канале (обычное дело в RU/EU),
  // ESP физически не может согласовать с ней подключение — и это выглядит
  // ровно как бесконечный AUTH_EXPIRE/NO_AP_FOUND, один в один как в наших
  // логах, причём одинаково на разных точках доступа. Явно разрешаем полный
  // диапазон 1–13, чтобы регион точно не был причиной.
  wifi_country_t country = {};
  strncpy(country.cc, "01", sizeof(country.cc));
  country.schan = 1;
  country.nchan = 13;
  country.max_tx_power = 20;
  country.policy = WIFI_COUNTRY_POLICY_MANUAL;
  esp_err_t err = esp_wifi_set_country(&country);
  Serial.printf("[WiFi] esp_wifi_set_country(1..13) -> %s\n",
                err == ESP_OK ? "ok" : "FAILED");
}

void ensureStationReady() {
  // WiFi.mode() переключает интерфейс асинхронно (сообщением в Wi-Fi таск).
  // Дожидаемся, пока режим реально применится, прежде чем трогать что-либо
  // ещё — иначе не только setSleep(), но и esp_wifi_set_country() ниже
  // может тихо не сработать (STA ещё не поднялась).
  WiFi.mode(WIFI_STA);
  const unsigned long modeWaitStart = millis();
  while (WiFi.getMode() != WIFI_STA && millis() - modeWaitStart < 1000) {
    delay(10);
  }

  relaxCountryChannelLimits();

  // Главный подозреваемый в текущей проблеме: снижаем TX-мощность, чтобы
  // не проваливаться в просадку питания на слабом стабилизаторе платы
  // (см. комментарий у WIFI_TX_POWER выше).
  const bool txPowerOk = WiFi.setTxPower(WIFI_TX_POWER);
  Serial.printf("[WiFi] setTxPower(8.5dBm) -> %s\n", txPowerOk ? "ok" : "FAILED");

  // Энергопотребление сейчас не важно — держим радио полностью активным
  // постоянно, а не только на время хендшейка. Так проще и без сюрпризов:
  // никакого динамического переключения режимов после коннекта, никакой
  // связанной с этим задержки доставки UDP.
  const bool sleepOk = WiFi.setSleep(WIFI_PS_NONE);
  Serial.printf("[WiFi] setSleep(NONE) -> %s\n", sleepOk ? "ok" : "FAILED");
}

void hardResetWiFi() {
  // Более тяжёлый сброс: стираем сохранённые в NVS креденшлы (вдруг там
  // накопился мусор от прошлых попыток) и держим радио выключенным дольше
  // обычного, чтобы гарантированно погасить любое зависшее внутреннее
  // состояние драйвера перед следующей попыткой.
  Serial.println("[WiFi] Hard reset: erasing stored credentials, power-cycling radio...");
  WiFi.disconnect(true, true);
  WiFi.mode(WIFI_OFF);
  delay(1000);
}

unsigned long wifiBackoffDelay(uint32_t consecutiveFailures) {
  unsigned long delayMs = WIFI_RETRY_BASE_DELAY_MS;
  for (uint32_t i = 1; i < consecutiveFailures && delayMs < WIFI_RETRY_MAX_DELAY_MS; ++i) {
    delayMs *= 2;
  }
  return delayMs > WIFI_RETRY_MAX_DELAY_MS ? WIFI_RETRY_MAX_DELAY_MS : delayMs;
}

void connectToWiFi() {
  WiFi.persistent(false);  // не насилуем NVS повторными begin()
  Serial.printf("[WiFi] MAC: %s\n", WiFi.macAddress().c_str());

  // ВАЖНО: намеренно НЕ трогаем WiFi.setAutoReconnect() — по умолчанию в
  // ядре arduino-esp32 он и так true. Раньше мы пробовали его выключать и
  // вручную повторять begin() сами — это дёргало begin() поверх ещё
  // активной попытки драйвера и рвало хендшейк ("sta is connecting, cannot
  // set config"). Стек сам неплохо переживает единичные обрывы —
  // мы просто ждём результата, не мешая ему, и добавляем свои, более
  // тяжёлые уровни восстановления поверх, если он застрял надолго.
  ensureStationReady();

  uint32_t attempt = 0;
  uint32_t consecutiveFailures = 0;
  while (true) {
    ++attempt;
    Serial.printf("[WiFi] Attempt %lu: connecting to \"%s\"...\n", attempt, WIFI_SSID);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    const unsigned long startedAt = millis();
    while (WiFi.status() != WL_CONNECTED &&
           millis() - startedAt < WIFI_CONNECT_TIMEOUT_MS) {
      tickConnectingUi();
    }

    if (WiFi.status() == WL_CONNECTED) {
      Serial.printf("[WiFi] Connected: IP=%s RSSI=%d dBm channel=%d txPower=%d\n",
                     WiFi.localIP().toString().c_str(), WiFi.RSSI(), WiFi.channel(),
                     (int)WiFi.getTxPower());
      return;
    }

    ++consecutiveFailures;
    Serial.printf("[WiFi] Attempt %lu failed after %lu ms (status=%d), consecutive failures=%lu\n",
                  attempt, WIFI_CONNECT_TIMEOUT_MS, (int)WiFi.status(), consecutiveFailures);

    if (consecutiveFailures >= WIFI_FULL_REBOOT_AFTER_FAILURES) {
      Serial.println("[WiFi] Too many consecutive failures — rebooting the MCU...");
      Serial.flush();
      delay(100);
      ESP.restart();
    }

    if (consecutiveFailures % WIFI_HARD_RESET_AFTER_FAILURES == 0) {
      hardResetWiFi();
    } else {
      WiFi.disconnect(true);
      delay(300);
    }
    ensureStationReady();

    const unsigned long pause = wifiBackoffDelay(consecutiveFailures);
    Serial.printf("[WiFi] Waiting %lu ms before next attempt...\n", pause);
    const unsigned long retryStartedAt = millis();
    while (millis() - retryStartedAt < pause) {
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
