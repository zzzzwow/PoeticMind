 #include <Wire.h>
#include "MAX30105.h"
#include <Adafruit_Thermal.h>

MAX30105 particleSensor;
Adafruit_Thermal printer(&Serial1);

const byte BUFFER_SIZE = 8;
unsigned long lastBeatTime = 0;
unsigned long rrIntervals[BUFFER_SIZE];
int rrCount = 0;
long irBuffer[3] = {0};
int irIndex = 0;

String receivedData = "";
bool timestampPrinted = false;
bool poemStarted = false;
unsigned long lastReceiveTime = 0;

void setup() {
  Serial.begin(9600);
  Serial1.begin(9600);  // 热敏打印机

  delay(2000);
  Serial.println("Arduino Ready");

  if (!particleSensor.begin(Wire, I2C_SPEED_FAST)) {
    Serial.println("MAX30105 not found.");
    while (1);
  }
  particleSensor.setup(0x1F, 8, 3, 100, 411, 4096);

  printer.begin();
  printer.setDefault();
  printer.setLineHeight(24);
  printer.justify('L');
}

void loop() {
  // ====== HRV 采集 ======
  long irValue = particleSensor.getIR();
  irBuffer[0] = irBuffer[1];
  irBuffer[1] = irBuffer[2];
  irBuffer[2] = irValue;

  if (irIndex >= 2) {
    if (irBuffer[1] > irBuffer[0] && irBuffer[1] > irBuffer[2]) {
      unsigned long now = millis();
      if (lastBeatTime > 0) {
        unsigned long rr = now - lastBeatTime;
        if (rr > 300 && rr < 2000) {
          rrIntervals[rrCount % BUFFER_SIZE] = rr;
          rrCount++;
          Serial.print("[Arduino] → RR:");
          Serial.println(rr);
        }
      }
      lastBeatTime = now;
    }
  } else {
    irIndex++;
  }

  if (rrCount >= BUFFER_SIZE) {
    float sumSq = 0;
    for (int i = 1; i < BUFFER_SIZE; i++) {
      long diff = rrIntervals[i] - rrIntervals[i - 1];
      sumSq += diff * diff;
    }
    float rmssd = sqrt(sumSq / (BUFFER_SIZE - 1));
    Serial.print("[Arduino] → rMSSD: ");
    Serial.println(rmssd);
    rrCount = 0;
  }

  // ====== 串口接收打印 ======
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      if (receivedData.length() > 0) {
        Serial.print("[Arduino] Received from Pi: ");
        Serial.println(receivedData);

        if (!timestampPrinted) {
          printer.println(receivedData);  // 打印时间
          printer.println("    ");
          timestampPrinted = true;
        } else {
          printWrappedLine(receivedData);  // 打印诗句
          printer.println("    ");
          poemStarted = true;
        }

        receivedData = "";
        lastReceiveTime = millis();
      }
    } else {
      receivedData += c;
    }
  }

  // ===== 打印结尾提示 =====
  if (poemStarted && (millis() - lastReceiveTime > 3000)) {
    printer.feed(2);
    printer.println("----- please tear off -----");
    printer.feed(7);
    Serial.println("printing finished");
    Serial.println("[Arduino] Print done.");
    printer.feed(2);
    poemStarted = false;
    timestampPrinted = false;
  }

  delay(4);
}

// 自动换行打印
void printWrappedLine(String text) {
  int maxChars = 32;
  int start = 0;
  while (start < text.length()) {
    int end = start + maxChars;
    if (end > text.length()) end = text.length();
    else {
      while (end > start && text[end] != ' ') end--;
      if (end == start) end = start + maxChars;
    }
    printer.println(text.substring(start, end));
    start = end + 1;
  }
}
