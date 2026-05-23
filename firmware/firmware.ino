#include <WiFi.h>
#include <ModbusIP_ESP8266.h>
#include <Wire.h>
#include <DHT.h>
#include "MAX30105.h"
#include "spo2_algorithm.h"
#include "ota_web.h"

/* WIFI */
const char* ssid = "KOSTMAMI 2";
const char* password = "kirana2017";

IPAddress ip(192, 168, 18, 254);
IPAddress gateway(192, 168, 18, 1);
IPAddress subnet(255, 255, 255, 0);
IPAddress dns(8, 8, 8, 8);

/* MODBUS */
#define REG_SPO2 1
#define REG_HR 2
#define REG_TEMP 3
#define REG_HUMIDITY 4
#define REG_GSR 5

/* PIN */
#define DHTPIN 7
#define DHTTYPE DHT11

#define GSR_PIN 2

#define SDA_PIN 8
#define SCL_PIN 9

/* OBJECT */
ModbusIP modbus;
DHT dht(DHTPIN, DHTTYPE);
MAX30105 particleSensor;

/* GLOBAL */
float temperature = 0;
float humidity = 0;
float gsrValue = 0;
int32_t spo2 = 0;
int32_t hr = 0;
uint32_t irBuffer[100];
uint32_t redBuffer[100];
int8_t validSPO2;
int8_t validHeartRate;

/* TIMER */
unsigned long lastMillis = 0;
const unsigned long INTERVAL = 3000;

/* WIFI */
void connectWiFi() {
  WiFi.config(ip, gateway, subnet, dns);
  WiFi.begin(ssid, password);
  Serial.print("Connecting");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();
  Serial.println("WiFi Connected");
  Serial.println(WiFi.localIP());
}

/* DHT */
void bacaDHT() {
  temperature = dht.readTemperature();
  humidity = dht.readHumidity();
  if (isnan(temperature)) temperature = 0;
  if (isnan(humidity)) humidity = 0;
}

/* GSR */
void bacaGSR() {
  int adc = analogRead(GSR_PIN);
  gsrValue = map(adc, 0, 4095, 0, 100);
}

/* MAX INIT */
void initMAX30105() {
  Wire.begin(SDA_PIN, SCL_PIN);
  if (!particleSensor.begin(Wire, I2C_SPEED_STANDARD)) {
    Serial.println("MAX30105 NOT FOUND");
    return;
  }
  Serial.println("MAX30105 READY");
  particleSensor.setup(
    60,
    4,
    2,
    100,
    411,
    4096);
}

/* SPO2 */
void bacaMAX30105() {
  for (int i = 0; i < 100; i++) {
    unsigned long timeout = millis();
    while (!particleSensor.available()) {
      particleSensor.check();
      yield();
      if (millis() - timeout > 250) {
        Serial.println("MAX Timeout");
        return;
      }
    }
    redBuffer[i] = particleSensor.getRed();
    irBuffer[i] = particleSensor.getIR();
    particleSensor.nextSample();
  }

  maxim_heart_rate_and_oxygen_saturation(
    irBuffer,
    100,
    redBuffer,
    &spo2,
    &validSPO2,
    &hr,
    &validHeartRate);

  if (!validHeartRate) hr = 0;
  if (!validSPO2) spo2 = 0;
}

/* SETUP */
void setup() {
  Serial.begin(115200);
  connectWiFi();
  dht.begin();
  initMAX30105();

  modbus.server();
  modbus.addIreg(REG_SPO2);
  modbus.addIreg(REG_HR);
  modbus.addIreg(REG_TEMP);
  modbus.addIreg(REG_HUMIDITY);
  modbus.addIreg(REG_GSR);

  setupOTA();
  Serial.println("SYSTEM READY");
  lastMillis = millis();
}

/* LOOP */
void loop() {
  modbus.task();
  handleOTA();
  if (millis() - lastMillis >= INTERVAL) {
    lastMillis = millis();
    bacaDHT();
    bacaGSR();
    bacaMAX30105();

    modbus.Ireg(REG_SPO2, spo2 * 10);
    modbus.Ireg(REG_HR, hr * 10);
    modbus.Ireg(REG_TEMP, temperature * 10);
    modbus.Ireg(REG_HUMIDITY, humidity * 10);
    modbus.Ireg(REG_GSR, gsrValue * 10);

    Serial.println("==========");
    Serial.print("SPO2 : ");
    Serial.println(spo2);
    Serial.print("HR : ");
    Serial.println(hr);
    Serial.print("TEMP : ");
    Serial.println(temperature);
    Serial.print("HUM : ");
    Serial.println(humidity);
    Serial.print("GSR : ");
    Serial.println(gsrValue);
  }

  yield();
  delay(20);
}