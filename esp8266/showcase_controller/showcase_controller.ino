/*
 * People Counter — ESP8266 Showcase Controller
 * ─────────────────────────────────────────────
 * Управляет 8 витринами через модуль PCA9685 (12-bit PWM).
 *
 * Подключение:
 *   PCA9685 по I2C:  D1 (GPIO5) = SCL,  D2 (GPIO4) = SDA
 *   Адрес PCA9685:   0x40 (по умолчанию, все A0-A5 = 0)
 *   К каналам PCA9685 подключены драйверы LED-лент витрин.
 *
 * Зависимости (Arduino Library Manager):
 *   - Adafruit PWM Servo Driver Library  (автоматически тянет Adafruit BusIO)
 *
 * UDP-протокол (порт CMD_PORT):
 *   ON            — авто-включение (камера зафиксировала людей)
 *                   Витрины загораются по очереди с плавным нарастанием.
 *   OFF           — авто-выключение (зал пуст)
 *                   Все авто-витрины гаснут одновременно, плавно.
 *   FON:1,3,5     — принудительно включить витрины 1,3,5 (нумерация с 1)
 *                   Горят независимо от режима камеры.
 *   FOFF:1,3,5    — снять принуждение с витрин 1,3,5
 *                   Если камера сейчас «пусто» — витрины плавно гаснут.
 *   MAP:1=0,2=3   — переназначить канал PCA9685 для витрины
 *                   Формат: витрина(1-8)=канал(0-15)
 *   STATUS        — вывести состояние в Serial
 *   1 / 0         — обратная совместимость: 1=ON, 0=OFF
 *
 * Broadcast-анонс "PCOUNTER_SHOW" → порт ANNOUNCE_PORT каждые 5 с.
 *
 * Плата: ESP8266 (NodeMCU / Wemos D1 Mini)
 * IDE:   Arduino IDE + esp8266 core
 */

#include <ESP8266WiFi.h>
#include <WiFiUdp.h>
#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>

// ════════════════════════════════════════════
//  Настройки WiFi — измените под свою сеть
// ════════════════════════════════════════════

const char* WIFI_SSID     = "Honor 8A";
const char* WIFI_PASSWORD = "qwerty123";

// ════════════════════════════════════════════
//  Сетевые параметры
// ════════════════════════════════════════════

const int  CMD_PORT      = 4210;        // Порт приёма команд от Python
const int  ANNOUNCE_PORT = 4211;        // Порт рассылки анонсов
const char* ANNOUNCE_MSG = "PCOUNTER_SHOW";
const unsigned long ANNOUNCE_INTERVAL  = 5000; // мс

// ════════════════════════════════════════════
//  PCA9685
// ════════════════════════════════════════════

Adafruit_PWMServoDriver pca = Adafruit_PWMServoDriver(0x40);

const int PWM_FREQ  = 1000;   // Гц (для LED-лент)
const int PWM_MAX   = 4095;   // 12-bit максимум
const int PWM_MIN   = 0;

// ════════════════════════════════════════════
//  Параметры анимации
// ════════════════════════════════════════════

const int  FADE_STEP_ON    = 60;   // Шаг яркости за тик при включении
const int  FADE_STEP_OFF   = 80;   // Шаг яркости за тик при выключении
const int  FADE_TICK_MS    = 15;   // Интервал тика (мс)
const int  SEQ_DELAY_MS    = 350;  // Пауза между запуском соседних витрин (мс)

// ════════════════════════════════════════════
//  Константы витрин
// ════════════════════════════════════════════

const int NUM_SHOWCASES = 8;

// ════════════════════════════════════════════
//  Состояние системы
// ════════════════════════════════════════════

// channelMap[i] = номер канала PCA9685 для витрины i (0-based)
int channelMap[NUM_SHOWCASES] = {0, 1, 2, 3, 4, 5, 6, 7};

int  curBrightness[NUM_SHOWCASES];   // Текущая яркость (0..PWM_MAX)
int  tgtBrightness[NUM_SHOWCASES];   // Целевая яркость

bool forcedOn[NUM_SHOWCASES];        // true = принудительно включена
bool autoMode = false;               // true = камера зафиксировала людей

// ── Последовательное включение ──
bool         seqActive   = false;
int          seqIndex    = 0;        // Следующая витрина в очереди
unsigned long seqNextMs  = 0;        // Время старта следующей

// ── Таймеры ──
unsigned long lastFadeTick = 0;
unsigned long lastAnnounce = 0;

WiFiUDP udp;

// ════════════════════════════════════════════
//  PCA9685: установить PWM витрины i
// ════════════════════════════════════════════

void setPWM(int showcase, int brightness) {
    brightness = constrain(brightness, PWM_MIN, PWM_MAX);
    pca.setPWM(channelMap[showcase], 0, brightness);
}

// ════════════════════════════════════════════
//  Обработчики команд
// ════════════════════════════════════════════

void cmdAutoOn() {
    autoMode = true;
    // Запускаем последовательное включение для витрин, которые ещё не горят
    seqActive  = true;
    seqIndex   = 0;
    seqNextMs  = millis();
    Serial.println("[CMD] AUTO ON → последовательное включение");
}

void cmdAutoOff() {
    autoMode   = false;
    seqActive  = false;           // Отмена незаконченного sequencing
    Serial.println("[CMD] AUTO OFF → гасим авто-витрины");
    for (int i = 0; i < NUM_SHOWCASES; i++) {
        if (!forcedOn[i]) {
            tgtBrightness[i] = PWM_MIN;
        }
    }
}

// Разбор строки "1,3,5" → массив 0-based индексов, возвращает кол-во
int parseList(const String& s, int* out) {
    int count = 0;
    int start = 0;
    for (int i = 0; i <= (int)s.length(); i++) {
        if (i == (int)s.length() || s[i] == ',') {
            if (i > start) {
                int v = s.substring(start, i).toInt() - 1; // 1-based → 0-based
                if (v >= 0 && v < NUM_SHOWCASES) out[count++] = v;
            }
            start = i + 1;
        }
    }
    return count;
}

void cmdForceOn(const String& arg) {
    int idxs[NUM_SHOWCASES];
    int n = parseList(arg, idxs);
    Serial.printf("[CMD] FON: принудительно ВКЛ %d витрин\n", n);
    for (int k = 0; k < n; k++) {
        int i = idxs[k];
        forcedOn[i]     = true;
        tgtBrightness[i] = PWM_MAX;
        Serial.printf("  Витрина %d → ПРИНУДИТЕЛЬНО (канал %d)\n", i+1, channelMap[i]);
    }
}

void cmdForceOff(const String& arg) {
    int idxs[NUM_SHOWCASES];
    int n = parseList(arg, idxs);
    Serial.printf("[CMD] FOFF: снимаем принуждение с %d витрин\n", n);
    for (int k = 0; k < n; k++) {
        int i = idxs[k];
        forcedOn[i] = false;
        // Если авто-режим выключен — витрина гаснет; если включён — остаётся гореть
        if (!autoMode) {
            tgtBrightness[i] = PWM_MIN;
        }
        // (Если autoMode=true, tgtBrightness уже = PWM_MAX, оставляем как есть)
        Serial.printf("  Витрина %d → авто (канал %d)\n", i+1, channelMap[i]);
    }
}

// MAP:1=0,2=3,4=7 — витрина(1-8) = канал PCA9685(0-15)
void cmdMap(const String& arg) {
    Serial.println("[CMD] MAP: перенастройка каналов");
    int start = 0;
    for (int i = 0; i <= (int)arg.length(); i++) {
        if (i == (int)arg.length() || arg[i] == ',') {
            String pair = arg.substring(start, i);
            int eq = pair.indexOf('=');
            if (eq > 0) {
                int showcase = pair.substring(0, eq).toInt() - 1; // 0-based
                int channel  = pair.substring(eq + 1).toInt();
                if (showcase >= 0 && showcase < NUM_SHOWCASES &&
                    channel  >= 0 && channel  < 16) {
                    // Переключить PCA9685: сначала погасить старый канал
                    pca.setPWM(channelMap[showcase], 0, PWM_MIN);
                    channelMap[showcase] = channel;
                    // Восстановить текущую яркость на новом канале
                    pca.setPWM(channel, 0, curBrightness[showcase]);
                    Serial.printf("  Витрина %d → канал %d\n", showcase+1, channel);
                }
            }
            start = i + 1;
        }
    }
}

void cmdStatus() {
    Serial.println("═══ STATUS ═══");
    Serial.printf("autoMode : %s\n", autoMode ? "ON" : "OFF");
    Serial.printf("seqActive: %s  seqIndex: %d\n", seqActive ? "yes" : "no", seqIndex);
    for (int i = 0; i < NUM_SHOWCASES; i++) {
        Serial.printf("  [%d] канал=%-2d  cur=%-4d  tgt=%-4d  forced=%s\n",
                      i+1, channelMap[i], curBrightness[i], tgtBrightness[i],
                      forcedOn[i] ? "YES" : "no ");
    }
    Serial.println("══════════════");
}

// ════════════════════════════════════════════
//  Диспетчер команд
// ════════════════════════════════════════════

void processCommand(const String& raw) {
    String cmd = raw;
    cmd.trim();
    Serial.printf("→ CMD: \"%s\"\n", cmd.c_str());

    if      (cmd == "ON"  || cmd == "1") { cmdAutoOn();  }
    else if (cmd == "OFF" || cmd == "0") { cmdAutoOff(); }
    else if (cmd.startsWith("FON:"))     { cmdForceOn(cmd.substring(4));  }
    else if (cmd.startsWith("FOFF:"))    { cmdForceOff(cmd.substring(5)); }
    else if (cmd.startsWith("MAP:"))     { cmdMap(cmd.substring(4));      }
    else if (cmd == "STATUS")            { cmdStatus(); }
    else {
        Serial.printf("  ? Неизвестная команда: \"%s\"\n", cmd.c_str());
    }
}

// ════════════════════════════════════════════
//  Последовательное включение (тик)
// ════════════════════════════════════════════

void tickSequential() {
    if (!seqActive) return;
    unsigned long now = millis();
    if (now < seqNextMs) return;

    // Ищем следующую витрину, которую нужно включить
    while (seqIndex < NUM_SHOWCASES) {
        int i = seqIndex;
        seqIndex++;
        bool shouldBeOn = autoMode || forcedOn[i];
        if (shouldBeOn && tgtBrightness[i] < PWM_MAX) {
            tgtBrightness[i] = PWM_MAX;
            Serial.printf("  [SEQ] Витрина %d → включение\n", i + 1);
            seqNextMs = now + SEQ_DELAY_MS;
            return; // Ждём паузу перед следующей
        }
        // Уже горит или не должна гореть → пропускаем мгновенно
    }

    // Все витрины обработаны
    seqActive = false;
    Serial.println("  [SEQ] Последовательное включение завершено");
}

// ════════════════════════════════════════════
//  Fade-тик: двигаем cur → tgt для всех витрин
// ════════════════════════════════════════════

void tickFade() {
    unsigned long now = millis();
    if (now - lastFadeTick < (unsigned long)FADE_TICK_MS) return;
    lastFadeTick = now;

    for (int i = 0; i < NUM_SHOWCASES; i++) {
        if (curBrightness[i] == tgtBrightness[i]) continue;

        int diff = tgtBrightness[i] - curBrightness[i];
        int step = (diff > 0) ? FADE_STEP_ON : -FADE_STEP_OFF;

        if (abs(diff) <= max(FADE_STEP_ON, FADE_STEP_OFF)) {
            curBrightness[i] = tgtBrightness[i];
        } else {
            curBrightness[i] += step;
        }
        curBrightness[i] = constrain(curBrightness[i], PWM_MIN, PWM_MAX);
        setPWM(i, curBrightness[i]);
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
    Serial.println("\n\n=== People Counter — Showcase Controller ===");

    // ── PCA9685 ──
    // SDA = D2 = GPIO4,  SCL = D1 = GPIO5
    Wire.begin(4, 5);
    pca.begin();
    pca.setOscillatorFrequency(27000000); // Коррекция частоты генератора
    pca.setPWMFreq(PWM_FREQ);
    delay(10);

    // Инициализация массивов
    for (int i = 0; i < NUM_SHOWCASES; i++) {
        curBrightness[i] = 0;
        tgtBrightness[i] = 0;
        forcedOn[i]      = false;
        setPWM(i, 0);
    }
    Serial.printf("  PCA9685 OK  (PWM %d Гц, каналы 0-%d)\n", PWM_FREQ, NUM_SHOWCASES-1);
    Serial.println("  Маппинг по умолчанию: витрина N → канал N-1");

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
    Serial.println("============================================\n");
    Serial.println("Команды: ON | OFF | FON:1,2 | FOFF:1,2 | MAP:1=3 | STATUS");
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
        char buf[128] = {0};
        int  len = udp.read(buf, sizeof(buf) - 1);
        buf[len] = '\0';
        processCommand(String(buf));
    }

    // ── Анимация ──
    tickSequential();
    tickFade();

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
