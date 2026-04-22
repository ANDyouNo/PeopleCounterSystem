/*
 * People Counter — ESP8266 Light Controller (общий свет)
 * ────────────────────────────────────────────────────────
 * Управляет реле общего освещения.
 * Подключается к той же локальной сети и слушает UDP-команды
 * на своём порту (отдельном от контроллера витрин).
 *
 * Подключение реле:
 *   RELAY_PIN (D5 / GPIO14)  →  IN реле
 *   3.3 В или 5 В            →  VCC реле
 *   GND                      →  GND реле
 *   Реле нормально-разомкнутое (NO) — замыкается при HIGH на IN.
 *   Если ваше реле инвертирует сигнал (активный LOW), замените
 *   RELAY_ACTIVE_HIGH = false.
 *
 * UDP-протокол (порт CMD_PORT = 4212):
 *   ON     — авто-включение (команда от Python после задержки offset)
 *   OFF    — авто-выключение
 *   FON    — принудительно включить (горит независимо от камеры)
 *   FOFF   — снять принуждение (если авто выключен — гасит реле)
 *   STATUS — вывести состояние в Serial
 *   1 / 0  — обратная совместимость: 1=ON, 0=OFF
 *
 * Broadcast-анонс "PCOUNTER_LIGHT" → порт ANNOUNCE_PORT каждые 5 с.
 *
 * Плата: ESP8266 (NodeMCU / Wemos D1 Mini)
 * IDE:   Arduino IDE + esp8266 core
 */

#include <ESP8266WiFi.h>
#include <WiFiUdp.h>

// ════════════════════════════════════════════
//  Настройки WiFi — измените под свою сеть
// ════════════════════════════════════════════

const char* WIFI_SSID     = "Honor 8A";
const char* WIFI_PASSWORD = "qwerty123";

// ════════════════════════════════════════════
//  Сетевые параметры
//  (ДРУГИЕ порты, чем у showcase_controller!)
// ════════════════════════════════════════════

const int  CMD_PORT      = 4212;        // Порт приёма команд от Python
const int  ANNOUNCE_PORT = 4213;        // Порт рассылки анонсов
const char* ANNOUNCE_MSG = "PCOUNTER_LIGHT";
const unsigned long ANNOUNCE_INTERVAL  = 5000; // мс

// ════════════════════════════════════════════
//  Реле
// ════════════════════════════════════════════

const int RELAY_PIN         = D5;    // GPIO14
const bool RELAY_ACTIVE_HIGH = false; // true = HIGH включает реле (NO)
                                     // false = LOW  включает реле (NC/инвертирующий модуль)

// ════════════════════════════════════════════
//  Состояние
// ════════════════════════════════════════════

bool relayOn  = false;   // Физическое состояние реле
bool forced   = false;   // Принудительный режим
bool autoMode = false;   // Авто-режим (управляется камерой через Python)

WiFiUDP udp;
unsigned long lastAnnounce = 0;

// ════════════════════════════════════════════
//  Управление реле
// ════════════════════════════════════════════

void setRelay(bool on) {
    relayOn = on;
    bool pinLevel = RELAY_ACTIVE_HIGH ? on : !on;
    digitalWrite(RELAY_PIN, pinLevel ? HIGH : LOW);
    Serial.printf("  Реле → %s\n", on ? "ВКЛ" : "ВЫКЛ");
}

void updateRelay() {
    // Реле должно гореть если принудительно включено ИЛИ авто-режим активен
    bool shouldBeOn = forced || autoMode;
    if (shouldBeOn != relayOn) {
        setRelay(shouldBeOn);
    }
}

// ════════════════════════════════════════════
//  Обработчики команд
// ════════════════════════════════════════════

void cmdAutoOn() {
    autoMode = true;
    Serial.println("[CMD] AUTO ON");
    updateRelay();
}

void cmdAutoOff() {
    autoMode = false;
    Serial.println("[CMD] AUTO OFF");
    updateRelay();
}

void cmdForceOn() {
    forced = true;
    Serial.println("[CMD] FORCE ON — принудительно включён");
    updateRelay();
}

void cmdForceOff() {
    forced = false;
    Serial.println("[CMD] FORCE OFF — принуждение снято");
    updateRelay();
}

void cmdStatus() {
    Serial.println("═══ STATUS ═══");
    Serial.printf("autoMode : %s\n", autoMode ? "ON"  : "OFF");
    Serial.printf("forced   : %s\n", forced   ? "YES" : "no");
    Serial.printf("relay    : %s\n", relayOn  ? "ON"  : "OFF");
    Serial.println("══════════════");
}

// ════════════════════════════════════════════
//  Диспетчер команд
// ════════════════════════════════════════════

void processCommand(const String& raw) {
    String cmd = raw;
    cmd.trim();
    Serial.printf("→ CMD: \"%s\"\n", cmd.c_str());

    if      (cmd == "ON"  || cmd == "1") cmdAutoOn();
    else if (cmd == "OFF" || cmd == "0") cmdAutoOff();
    else if (cmd == "FON")               cmdForceOn();
    else if (cmd == "FOFF")              cmdForceOff();
    else if (cmd == "STATUS")            cmdStatus();
    else {
        Serial.printf("  ? Неизвестная команда: \"%s\"\n", cmd.c_str());
    }
}

// ════════════════════════════════════════════
//  Broadcast-анонс
// ════════════════════════════════════════════

void sendAnnounce() {
    IPAddress bcast = WiFi.localIP();
    bcast[3] = 255;
    udp.beginPacket(bcast, ANNOUNCE_PORT);
    udp.print(ANNOUNCE_MSG);
    udp.endPacket();
}

// ════════════════════════════════════════════
//  setup
// ════════════════════════════════════════════

void setup() {
    Serial.begin(115200);
    delay(100);
    Serial.println("\n\n=== People Counter — Light Controller ===");

    // ── Реле ──
    pinMode(RELAY_PIN, OUTPUT);
    setRelay(false);
    Serial.printf("  Реле: пин D5 (GPIO%d)  активный уровень: %s\n",
                  RELAY_PIN, RELAY_ACTIVE_HIGH ? "HIGH" : "LOW");

    // ── LED ──
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, HIGH);

    // ── WiFi ──
    Serial.printf("Подключение к \"%s\"", WIFI_SSID);
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    while (WiFi.status() != WL_CONNECTED) {
        delay(400); digitalWrite(LED_BUILTIN, LOW);
        delay(100); digitalWrite(LED_BUILTIN, HIGH);
        Serial.print(".");
    }
    Serial.print("\nWiFi ОК  IP: ");
    Serial.println(WiFi.localIP());

    // Отключаем modem-sleep — без этого ESP8266 «засыпает» между DTIM-маяками
    // и входящие UDP-пакеты задерживаются на 1–3 секунды.
    WiFi.setSleepMode(WIFI_NONE_SLEEP);

    // ── UDP ──
    udp.begin(CMD_PORT);
    Serial.printf("UDP слушает : %d\n", CMD_PORT);
    Serial.printf("Анонс       : broadcast:%d каждые %lu с\n",
                  ANNOUNCE_PORT, ANNOUNCE_INTERVAL / 1000);
    Serial.println("=========================================\n");
    Serial.println("Команды: ON | OFF | FON | FOFF | STATUS");
    Serial.println();

    sendAnnounce();
    lastAnnounce = millis();
}

// ════════════════════════════════════════════
//  loop
// ════════════════════════════════════════════

void loop() {

    // ── Приём UDP ──
    int pktSize = udp.parsePacket();
    if (pktSize > 0) {
        char buf[32] = {0};
        int  len = udp.read(buf, sizeof(buf) - 1);
        buf[len] = '\0';
        processCommand(String(buf));
    }

    // ── Анонс ──
    unsigned long now = millis();
    if (now - lastAnnounce >= ANNOUNCE_INTERVAL) {
        lastAnnounce = now;
        sendAnnounce();
    }

    // ── Мигание LED ("жив") ──
    static unsigned long lastBlink = 0;
    static bool ledState = false;
    if (now - lastBlink >= 3000) {
        lastBlink = now;
        ledState  = !ledState;
        digitalWrite(LED_BUILTIN, ledState ? LOW : HIGH);
    }
}
