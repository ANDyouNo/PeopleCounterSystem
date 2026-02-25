/*
 * People Counter — ESP8266 Executor
 * ------------------------------------
 * Роль: исполнитель команд от основного кода (Python).
 *
 * Что делает:
 *   1. Подключается к WiFi.
 *   2. Слушает UDP-команды на порту CMD_PORT:
 *        "1"  →  OUTPUT_PIN = HIGH  (включить)
 *        "0"  →  OUTPUT_PIN = LOW   (выключить)
 *   3. Каждые ANNOUNCE_INTERVAL мс рассылает UDP broadcast-анонс
 *      "PCOUNTER_ESP" на порт ANNOUNCE_PORT, чтобы основной код
 *      мог автоматически найти ESP в локальной сети.
 *
 * Плата: ESP8266 (NodeMCU, Wemos D1 Mini и др.)
 * IDE:   Arduino IDE + пакет esp8266 (https://arduino.esp8266.com/stable/package_esp8266com_index.json)
 *
 * Распиновка NodeMCU:
 *   D0=GPIO16  D1=GPIO5  D2=GPIO4  D3=GPIO0
 *   D4=GPIO2   D5=GPIO14 D6=GPIO12 D7=GPIO13  D8=GPIO15
 */

#include <ESP8266WiFi.h>
#include <WiFiUdp.h>

// ════════════════════════════════════════
//  Настройки — измените под себя
// ════════════════════════════════════════

const char* WIFI_SSID     = "Honor 8A";
const char* WIFI_PASSWORD = "qwerty123";

const int OUTPUT_PIN = D1;          // Управляемый пин (D1 = GPIO5)
                                    // Подключите реле или другой исполнитель

const int CMD_PORT      = 4210;     // Порт приёма команд от Python
const int ANNOUNCE_PORT = 4211;     // Порт рассылки анонсов (Python слушает его)

const char* ANNOUNCE_MSG      = "PCOUNTER_ESP";
const unsigned long ANNOUNCE_INTERVAL = 5000;   // Анонс каждые 5 секунд

// ════════════════════════════════════════
//  Переменные
// ════════════════════════════════════════

WiFiUDP udp;
unsigned long lastAnnounce = 0;
bool pinState = false;

// ════════════════════════════════════════
//  Вспомогательные функции
// ════════════════════════════════════════

void setPin(bool on) {
    pinState = on;
    digitalWrite(OUTPUT_PIN, on ? HIGH : LOW);
    Serial.print(on ? "  → ВКЛ  (pin=" : "  → ВЫКЛ (pin=");
    Serial.print(OUTPUT_PIN);
    Serial.println(")");
}

void sendAnnounce() {
    IPAddress broadcastIP = WiFi.localIP();
    broadcastIP[3] = 255;
    udp.beginPacket(broadcastIP, ANNOUNCE_PORT);
    udp.print(ANNOUNCE_MSG);
    udp.endPacket();
}

// ════════════════════════════════════════
//  setup
// ════════════════════════════════════════

void setup() {
    Serial.begin(115200);
    delay(100);
    Serial.println("\n\n=== People Counter ESP8266 ===");

    // Пин
    pinMode(OUTPUT_PIN, OUTPUT);
    setPin(false);

    // Встроенный LED — мигает пока ищет WiFi
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, HIGH);   // HIGH = выкл у большинства ESP

    // WiFi
    Serial.printf("Подключение к \"%s\"", WIFI_SSID);
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    while (WiFi.status() != WL_CONNECTED) {
        delay(400);
        digitalWrite(LED_BUILTIN, LOW);
        delay(100);
        digitalWrite(LED_BUILTIN, HIGH);
        Serial.print(".");
    }

    Serial.println("\nWiFi подключён!");
    Serial.print("IP: ");
    Serial.println(WiFi.localIP());

    // UDP
    udp.begin(CMD_PORT);
    Serial.printf("UDP слушает порт: %d\n", CMD_PORT);
    Serial.printf("Анонс → broadcast:%d каждые %lus\n",
                  ANNOUNCE_PORT, ANNOUNCE_INTERVAL / 1000);
    Serial.println("==============================\n");

    // Первый анонс сразу
    sendAnnounce();
    lastAnnounce = millis();
}

// ════════════════════════════════════════
//  loop
// ════════════════════════════════════════

void loop() {

    // ── Приём команды ──────────────────
    int packetSize = udp.parsePacket();
    if (packetSize > 0) {
        char buf[8] = {0};
        int len = udp.read(buf, sizeof(buf) - 1);
        buf[len] = '\0';

        String cmd = String(buf);
        cmd.trim();

        if (cmd == "1") {
            setPin(true);
        } else if (cmd == "0") {
            setPin(false);
        } else {
            Serial.printf("  ? Неизвестная команда: \"%s\"\n", buf);
        }
    }

    // ── Broadcast-анонс ────────────────
    unsigned long now = millis();
    if (now - lastAnnounce >= ANNOUNCE_INTERVAL) {
        lastAnnounce = now;
        sendAnnounce();
    }

    // ── Мигание LED = "жив" ────────────
    // Быстро моргает раз в 3 сек
    static unsigned long lastBlink = 0;
    static bool ledState = false;
    if (now - lastBlink >= 3000) {
        lastBlink = now;
        ledState = !ledState;
        digitalWrite(LED_BUILTIN, ledState ? LOW : HIGH);
    }
}
