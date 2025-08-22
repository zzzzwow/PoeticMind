#include <Wire.h>
#include "MAX30105.h"          // For MAX30102 via MAX30105 library
#include <Adafruit_Thermal.h>  // For TTL thermal printer

/***** === Devices === *****/
MAX30105 particleSensor;
Adafruit_Thermal printer(&Serial1);

/***** === HRV (rMSSD) === *****/
const byte HRV_BUF_SIZE = 8;             // ring buffer for RR
unsigned long lastBeatTime = 0;          // ms
unsigned long rrIntervals[HRV_BUF_SIZE]; // ms
int rrCount = 0;
long irBuffer[3] = {0, 0, 0};            // 3-sample local peak detector
int irIndex = 0;

/***** === Printer / Serial Receive === *****/
String receivedData = "";
bool timestampPrinted = false;  

/***** === GSR / ΔEDA === *****/
// Pin & ADC
const int GSR_PIN = A2;
const uint8_t ADC_BITS = 12;                // 0..4095
const float ADC_MAX = 4095.0f;

// Sampling: 25 Hz (40 ms)
const unsigned long GSR_SAMPLE_DT_MS = 40;  // 25 Hz
unsigned long lastGsrSampleMs = 0;

// Light oversampling x4 to reduce jitter
const int GSR_OVERSAMPLE = 4;

// EMA smoothing (tonic-like SCL) with tau ≈ 0.7 s
// alpha = dt / (tau + dt). dt=0.04s, tau=0.7s => alpha ≈ 0.04 / 0.74 ≈ 0.05405
const float EMA_ALPHA = 0.05405f;
bool emaInitialized = false;
float scl_norm = 0.0f;

// Epoching: 3-second non-overlapping windows -> 3 s * 25 Hz = 75 samples
const int EPOCH_LEN = 75;
int epochSampleCount = 0;
float epochSum = 0.0f;
bool baselineLocked = false;
float baselineMean = 0.0f;

// Utility
float clamp01(float x) { return x < 0 ? 0 : (x > 1 ? 1 : x); }

/***** === Helper: rMSSD computation === *****/
bool computeRMSSD(float &out_rMSSD_ms) {
  // Need at least 8 RR values: compute successive diff of (N-1)
  if (rrCount < HRV_BUF_SIZE) return false;
  double sumSq = 0.0;
  for (int i = 1; i < HRV_BUF_SIZE; ++i) {
    long diff = (long)rrIntervals[i] - (long)rrIntervals[i - 1]; // ms
    sumSq += (double)diff * (double)diff;
  }
  double meanSq = sumSq / (HRV_BUF_SIZE - 1);
  out_rMSSD_ms = (float)sqrt(meanSq);
  return true;
}

/***** === Setup === *****/
void setup() {
  // USB Serial to Raspberry Pi
  Serial.begin(115200);
  while (!Serial) { ; } // wait for native USB

  // I2C / MAX30102
  Wire.begin();
  if (!particleSensor.begin(Wire, I2C_SPEED_FAST)) {
    Serial.println(F("[ERR] MAX30102 not found. Check wiring."));
  } else {
    // Reasonable default config
    particleSensor.setup();                 // default setup
    particleSensor.setPulseAmplitudeRed(0); // we use IR only
    particleSensor.setPulseAmplitudeIR(0x2F);
  }

  // GSR ADC
  analogReadResolution(ADC_BITS); // 0..4095 on Nano 33 IoT

  // Thermal printer @ 19200 (common)
  Serial1.begin(19200);
  delay(100);
  printer.begin();
  printer.setDefault();
  printer.setLineHeight(24);
  printer.justify('L');

  Serial.println(F("[OK] System init complete."));
}

/***** === Printing helper: wrap 32 chars/line === *****/
void printWrappedLine(const String &text) {
  const int maxChars = 32;
  int start = 0;
  int n = text.length();
  while (start < n) {
    int end = start + maxChars;
    if (end >= n) {
      printer.println(text.substring(start));
      break;
    }
    // try break on space
    int p = end;
    while (p > start && text[p] != ' ') p--;
    if (p == start) p = end; // no space found, hard cut
    printer.println(text.substring(start, p));
    start = p + 1;
  }
}

/***** === Loop === *****/
void loop() {
  /***** 1) HRV acquisition (local-peak, RR filter, rMSSD) *****/
  long irValue = particleSensor.getIR();
  irBuffer[0] = irBuffer[1];
  irBuffer[1] = irBuffer[2];
  irBuffer[2] = irValue;

  if (irIndex >= 2) {
    // local peak: center greater than neighbors
    if (irBuffer[1] > irBuffer[0] && irBuffer[1] > irBuffer[2]) {
      unsigned long now = millis();
      if (lastBeatTime > 0) {
        unsigned long rr = now - lastBeatTime; // ms
        // keep only 300–2000 ms (≈30–200 bpm)
        if (rr >= 300 && rr <= 2000) {
          if (rrCount < HRV_BUF_SIZE) {
            rrIntervals[rrCount++] = rr;
          } else {
            // shift left (ring-like with simple shift to preserve order)
            for (int i = 1; i < HRV_BUF_SIZE; ++i) rrIntervals[i - 1] = rrIntervals[i];
            rrIntervals[HRV_BUF_SIZE - 1] = rr;
          }
          // Debug RR 
          // Serial.print(F("RR(ms): ")); Serial.println(rr);
          // Compute rMSSD when enough data
          float rMSSD_ms;
          if (computeRMSSD(rMSSD_ms)) {
            Serial.print(F("{\"type\":\"HRV\",\"rMSSD_ms\":"));
            Serial.print(rMSSD_ms, 2);
            Serial.println(F("}"));
          }
        }
      }
      lastBeatTime = now;
    }
  }
  irIndex++;

  /***** 2) GSR sampling @ 25 Hz -> EMA -> 3s epochs -> ΔEDA *****/
  unsigned long tnow = millis();
  if (tnow - lastGsrSampleMs >= GSR_SAMPLE_DT_MS) {
    lastGsrSampleMs += GSR_SAMPLE_DT_MS;

    // Light oversampling (x4)
    uint32_t acc = 0;
    for (int k = 0; k < GSR_OVERSAMPLE; ++k) {
      acc += (uint32_t)analogRead(GSR_PIN);
      delayMicroseconds(200); // tiny gap
    }
    float adc = (float)acc / (float)GSR_OVERSAMPLE; // 0..4095
    float norm = clamp01(adc / ADC_MAX);

    // EMA smoothing for SCL-like trace
    if (!emaInitialized) {
      scl_norm = norm;
      emaInitialized = true;
    } else {
      scl_norm = scl_norm + EMA_ALPHA * (norm - scl_norm);
    }

    // Epoch accumulation
    epochSum += scl_norm;
    epochSampleCount++;

    if (epochSampleCount >= EPOCH_LEN) {
      float epochMean = epochSum / (float)EPOCH_LEN;

      if (!baselineLocked) {
        baselineMean = epochMean;  // first complete epoch as baseline
        baselineLocked = true;
        Serial.print(F("{\"type\":\"EDA_BASELINE\",\"baseline\":"));
        Serial.print(baselineMean, 6);
        Serial.println(F("}"));
      } else {
        float deltaEDA = epochMean - baselineMean; // ΔEDA
        Serial.print(F("{\"type\":\"EDA\",\"delta\":"));
        Serial.print(deltaEDA, 6);
        Serial.println(F("}"));
      }

      // reset for next non-overlapping epoch
      epochSum = 0.0f;
      epochSampleCount = 0;
    }
  }

  /***** 3) Receive lines from Raspberry Pi and print *****/
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      if (receivedData.length() > 0) {
        if (!timestampPrinted) {
          timestampPrinted = true;
        }
        printWrappedLine(receivedData);
        receivedData = "";
      }
    } else {
      receivedData += c;
    }
  }
}
