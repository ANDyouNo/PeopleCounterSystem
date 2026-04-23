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
 *   ON            — авто-включение (последовательное, с плавным нарастанием)
 *   OFF           — авто-выключение (все гаснут плавно)
 *   FON:1,3,5     — принудительно включить витрины 1,3,5 (нумерация с 1)
 *   FOFF:1,3,5    — снять принуждение с витрин 1,3,5
 *   MAP:1=0,2=3   — переназначить канал PCA9685 для витрины
 *   STATUS        — вывести состояние в Serial
 *   1 / 0         — обратная совместимость: 1=ON, 0=OFF
 *
 *   — Режим прямого управления (Effects) —
 *   MODE:direct   — Python берёт управление PWM напрямую
 *                   Начинается watchdog: нет пакетов 3с → все каналы 0
 *   MODE:auto     — вернуться в автоматический режим (ON/OFF/FON/FOFF)
 *   PWM:0=4095,1=3200,2=0,...
 *                 — установить PWM каждого PCA-канала напрямую (0-15, 0-4095)
 *                   Сбрасывает watchdog. Только в MODE:direct.
 *   KA            — keepalive: сбросить watchdog без изменения значений
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

const int  CMD_PORT      = 4210;
const int  ANNOUNCE_PORT = 4211;
const char* ANNOUNCE_MSG = "PCOUNTER_SHOW";
const unsigned long ANNOUNCE_INTERVAL = 5000;  // мс

// ════════════════════════════════════════════
//  PCA9685
// ════════════════════════════════════════════

Adafruit_PWMServoDriver pca = Adafruit_PWMServoDriver(0x40);

const int PWM_FREQ = 1000;   // Гц (для LED-лент)
const int PWM_MAX  = 4095;   // 12-bit максимум
const int PWM_MIN  = 0;

// ════════════════════════════════════════════
//  Параметры анимации (автоматический режим)
// ════════════════════════════════════════════

const int  FADE_STEP_ON    = 60;   // Шаг яркости за тик при включении
const int  FADE_STEP_OFF   = 80;   // Шаг яркости за тик при выключении
const int  FADE_TICK_MS    = 15;   // Интервал тика (мс)
const int  SEQ_DELAY_MS    = 350;  // Пауза между запуском соседних витрин (мс)

// ════════════════════════════════════════════
//  Watchdog для режима direct (effects)
// ════════════════════════════════════════════

const unsigned long PWM_WATCHDOG_MS = 3000;  // 3 секунды без пакетов → все 0

// ════════════════════════════════════════════
//  Константы витрин
// ════════════════════════════════════════════

const int NUM_SHOWCASES = 8;

// ════════════════════════════════════════════
//  Состояние системы
// ════════════════════════════════════════════

// channelMap[i] = номер канала PCA9685 для витрины i (0-based)
// Каналы изменены специяльно.   1. 2. 3. 4. 5. 6. 7. 8. 
int channelMap[NUM_SHOWCASES] = {0, 1, 2, 3, 5, 7, 6, 4};

int  curBrightness[NUM_SHOWCASES];   // Текущая яркость (0..PWM_MAX)
int  tgtBrightness[NUM_SHOWCASES];   // Целевая яркость (автоматический режим)

bool forcedOn[NUM_SHOWCASES];        // true = принудительно включена
bool autoMode = false;               // true = камера зафиксировала людей

// ── Режим прямого управления (Effects) ──
bool          directMode     = false;
int           directPWM[NUM_SHOWCASES] = {0};  // PWM-значения витрин (индекс = витрина, не PCA-канал)
unsigned long lastPktTime    = 0;    // Время последнего пакета в direct-режиме

// ── Последовательное включение ──
bool          seqActive   = false;
int           seqIndex    = 0;
unsigned long seqNextMs   = 0;

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

// Установить PWM напрямую по номеру канала PCA (0-15)
void setChannelPWM(int channel, int value) {
    value = constrain(value, PWM_MIN, PWM_MAX);
    pca.setPWM(channel, 0, value);
}

// Погасить все 16 каналов PCA9685
void allChannelsOff() {
    for (int ch = 0; ch < 16; ch++) {
        pca.setPWM(ch, 0, PWM_MIN);
    }
    for (int i = 0; i < NUM_SHOWCASES; i++) {
        curBrightness[i] = 0;
        tgtBrightness[i] = 0;
    }
    for (int s = 0; s < NUM_SHOWCASES; s++) {
        directPWM[s] = 0;
    }
}

// ════════════════════════════════════════════
//  Обработчики автоматических команд
// ════════════════════════════════════════════

void cmdAutoOn() {
    autoMode  = true;
    seqActive = true;
    seqIndex  = 0;
    seqNextMs = millis();
    Serial.println("[CMD] AUTO ON → последовательное включение");
}

void cmdAutoOff() {
    autoMode  = false;
    seqActive = false;
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
                int v = s.substring(start, i).toInt() - 1;
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
    for (int k = 0; k < n; k++) {
        int i = idxs[k];
        forcedOn[i]      = true;
        tgtBrightness[i] = PWM_MAX;
    }
    Serial.printf("[CMD] FON: %d витрин\n", n);
}

void cmdForceOff(const String& arg) {
    int idxs[NUM_SHOWCASES];
    int n = parseList(arg, idxs);
    for (int k = 0; k < n; k++) {
        int i = idxs[k];
        forcedOn[i] = false;
        if (!autoMode) tgtBrightness[i] = PWM_MIN;
    }
    Serial.printf("[CMD] FOFF: %d витрин\n", n);
}

void cmdMap(const String& arg) {
    int start = 0;
    for (int i = 0; i <= (int)arg.length(); i++) {
        if (i == (int)arg.length() || arg[i] == ',') {
            String pair = arg.substring(start, i);
            int eq = pair.indexOf('=');
            if (eq > 0) {
                int showcase = pair.substring(0, eq).toInt() - 1;
                int channel  = pair.substring(eq + 1).toInt();
                if (showcase >= 0 && showcase < NUM_SHOWCASES &&
                    channel  >= 0 && channel  < 16) {
                    pca.setPWM(channelMap[showcase], 0, PWM_MIN);
                    channelMap[showcase] = channel;
                    pca.setPWM(channel, 0, curBrightness[showcase]);
                }
            }
            start = i + 1;
        }
    }
    Serial.println("[CMD] MAP: каналы обновлены");
}

void cmdStatus() {
    Serial.println("═══ STATUS ═══");
    Serial.printf("mode     : %s\n", directMode ? "DIRECT" : (autoMode ? "AUTO-ON" : "AUTO-OFF"));
    Serial.printf("seqActive: %s  seqIndex: %d\n", seqActive ? "yes" : "no", seqIndex);
    if (directMode) {
        Serial.printf("watchdog : %lu мс назад\n", millis() - lastPktTime);
        for (int s = 0; s < NUM_SHOWCASES; s++) {
            Serial.printf("  showcase[%d] -> PCA ch%02d = %d\n", s, channelMap[s], directPWM[s]);
        }
    } else {
        for (int i = 0; i < NUM_SHOWCASES; i++) {
            Serial.printf("  [%d] ch=%-2d  cur=%-4d  tgt=%-4d  forced=%s\n",
                          i+1, channelMap[i], curBrightness[i], tgtBrightness[i],
                          forcedOn[i] ? "YES" : "no ");
        }
    }
    Serial.println("══════════════");
}

// ════════════════════════════════════════════
//  Обработчики команд прямого управления
// ════════════════════════════════════════════

// PWM:0=4095,1=3200,7=0,...
// Индексы — витрины (0..NUM_SHOWCASES-1), маппинг на PCA каналы через channelMap
void cmdPWM(const String& arg) {
    lastPktTime = millis();
    int start = 0;
    for (int i = 0; i <= (int)arg.length(); i++) {
        if (i == (int)arg.length() || arg[i] == ',') {
            String pair = arg.substring(start, i);
            int eq = pair.indexOf('=');
            if (eq > 0) {
                int showcase = pair.substring(0, eq).toInt();
                int val      = pair.substring(eq + 1).toInt();
                if (showcase >= 0 && showcase < NUM_SHOWCASES) {
                    val = constrain(val, PWM_MIN, PWM_MAX);
                    directPWM[showcase]    = val;
                    curBrightness[showcase] = val;
                    setPWM(showcase, val);  // проходит через channelMap!
                }
            }
            start = i + 1;
        }
    }
}

void cmdModeSwitch(const String& arg) {
    if (arg == "direct") {
        directMode  = true;
        lastPktTime = millis();
        Serial.println("[CMD] MODE:direct — Python взял управление PWM");
    } else if (arg == "auto") {
        directMode = false;
        Serial.println("[CMD] MODE:auto — возврат в автоматический режим");
        // Восстанавливаем состояние витрин по autoMode/forcedOn
        for (int i = 0; i < NUM_SHOWCASES; i++) {
            bool shouldOn = autoMode || forcedOn[i];
            tgtBrightness[i] = shouldOn ? PWM_MAX : PWM_MIN;
        }
    }
}

// ════════════════════════════════════════════
//  Диспетчер команд
// ════════════════════════════════════════════

void processCommand(const String& raw) {
    String cmd = raw;
    cmd.trim();

    // В direct-режиме любой пакет (кроме MODE:auto) сбрасывает watchdog
    if (directMode && cmd != "MODE:auto") {
        lastPktTime = millis();
    }

    if      (cmd == "ON"  || cmd == "1")    { if (!directMode) cmdAutoOn();  }
    else if (cmd == "OFF" || cmd == "0")    { if (!directMode) cmdAutoOff(); }
    else if (cmd.startsWith("FON:"))        { if (!directMode) cmdForceOn(cmd.substring(4));  }
    else if (cmd.startsWith("FOFF:"))       { if (!directMode) cmdForceOff(cmd.substring(5)); }
    else if (cmd.startsWith("MAP:"))        { cmdMap(cmd.substring(4));   }
    else if (cmd.startsWith("PWM:"))        { if (directMode) cmdPWM(cmd.substring(4)); }
    else if (cmd.startsWith("MODE:"))       { cmdModeSwitch(cmd.substring(5)); }
    else if (cmd == "KA")                   { /* keepalive — watchdog уже сброшен выше */ }
    else if (cmd == "STATUS")               { cmdStatus(); }
    else {
        Serial.printf("  ? Неизвестная команда: \"%s\"\n", cmd.c_str());
    }
}

// ════════════════════════════════════════════
//  Watchdog проверка (direct-режим)
// ════════════════════════════════════════════

void tickWatchdog() {
    if (!directMode) return;
    if (millis() - lastPktTime > PWM_WATCHDOG_MS) {
        Serial.println("[WATCHDOG] Нет пакетов 3с → все каналы выключены, возврат в AUTO");
        allChannelsOff();
        directMode = false;
        autoMode   = false;
    }
}

// ════════════════════════════════════════════
//  Последовательное включение (тик)
// ════════════════════════════════════════════

void tickSequential() {
    if (!seqActive || directMode) return;
    unsigned long now = millis();
    if (now < seqNextMs) return;

    while (seqIndex < NUM_SHOWCASES) {
        int i = seqIndex;
        seqIndex++;
        bool shouldBeOn = autoMode || forcedOn[i];
        if (shouldBeOn && tgtBrightness[i] < PWM_MAX) {
            tgtBrightness[i] = PWM_MAX;
            seqNextMs = now + SEQ_DELAY_MS;
            return;
        }
    }
    seqActive = false;
}

// ════════════════════════════════════════════
//  Fade-тик (только в автоматическом режиме)
// ════════════════════════════════════════════

void tickFade() {
    if (directMode) return;
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
    Wire.begin(4, 5);
    pca.begin();
    pca.setOscillatorFrequency(27000000);
    pca.setPWMFreq(PWM_FREQ);
    delay(10);

    for (int i = 0; i < NUM_SHOWCASES; i++) {
        curBrightness[i] = 0;
        tgtBrightness[i] = 0;
        forcedOn[i]      = false;
        setPWM(i, 0);
    }
    for (int s = 0; s < NUM_SHOWCASES; s++) directPWM[s] = 0;

    Serial.printf("  PCA9685 OK  (PWM %d Гц, каналы 0-%d)\n", PWM_FREQ, NUM_SHOWCASES - 1);

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
    Serial.print("\nWiFi OK  IP: ");
    Serial.println(WiFi.localIP());
    WiFi.setSleepMode(WIFI_NONE_SLEEP);

    // ── UDP ──
    udp.begin(CMD_PORT);
    Serial.printf("UDP: порт %d\n", CMD_PORT);
    Serial.printf("Анонс: broadcast:%d каждые %lus\n", ANNOUNCE_PORT, ANNOUNCE_INTERVAL / 1000);
    Serial.println("Команды: ON|OFF|FON:1,2|FOFF:1,2|MAP:1=3|MODE:direct|MODE:auto|PWM:0=4095|KA|STATUS");
    Serial.println("============================================\n");

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
        char buf[256] = {0};
        int  len = udp.read(buf, sizeof(buf) - 1);
        buf[len] = '\0';
        processCommand(String(buf));
    }

    // ── Watchdog ──
    tickWatchdog();

    // ── Анимация (только в auto-режиме) ──
    tickSequential();
    tickFade();

    // ── Анонс ──
    unsigned long now = millis();
    if (now - lastAnnounce >= ANNOUNCE_INTERVAL) {
        lastAnnounce = now;
        sendAnnounce();
    }

    // ── Мигание LED ──
    static unsigned long lastBlink = 0;
    static bool ledState = false;
    if (now - lastBlink >= 3000) {
        lastBlink = now;
        ledState  = !ledState;
        digitalWrite(LED_BUILTIN, ledState ? LOW : HIGH);
    }
}
