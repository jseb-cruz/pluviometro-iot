// Pluviometro gravimetrico IoT - firmware de adquisicion y envio (BORRADOR v0.1)
// ESP32 + HX711 + potenciometro con flotador -> AWS IoT Core (MQTT sobre TLS, puerto 8883)
//
// Tratamiento de la senal (en este orden):
//   1. Mediana de 5 muestras  -> elimina picos por golpes de gotas
//   2. Media exponencial (EMA) -> suaviza el ruido
//   3. Calibracion            -> masa = (raw - offset) / factor
//   4. Correccion             -> x = (medido - b) / a  y compensacion de drift
//   5. Validacion             -> rango fisico y cruce celda / potenciometro
//
// Librerias: HX711 (Bogdan Necula), PubSubClient (Nick O'Leary), ArduinoJson (Benoit Blanchon, v7)
// Archivos: config.h (WiFi y constantes) y aws_secrets.h (lo genera Terraform)

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <time.h>
#include "HX711.h"
#include "config.h"
#include "aws_secrets.h"

HX711 hx;
WiFiClientSecure red;
PubSubClient mqtt(red);

// ---------------- Estado del tratamiento de la senal ----------------
long ventana[5];
int  idxVentana = 0;
bool ventanaLlena = false;

double emaRaw = 0;            // paso 2
bool   emaIniciada = false;
double masaAnterior = 0;      // para detectar saltos imposibles
double mmAnteriorPub = 0;     // para la tasa de lluvia
unsigned long msAnteriorPub = 0;
unsigned long ultimoEnvio = 0;
unsigned long secuencia = 0;
bool simularDrift = false;    // se activa con el comando "d" por el monitor serie
long offsetActual = CAL_OFFSET; // se puede rehacer la tara con el comando "t"

// ---------------- Paso 1: mediana de 5 ----------------
long mediana5(long *v) {
  long a[5];
  for (int i = 0; i < 5; i++) a[i] = v[i];
  for (int i = 1; i < 5; i++) {           // insercion: 5 elementos, es suficiente
    long x = a[i]; int j = i - 1;
    while (j >= 0 && a[j] > x) { a[j + 1] = a[j]; j--; }
    a[j + 1] = x;
  }
  return a[2];
}

double leerPotMv() {
  long suma = 0;
  for (int i = 0; i < 16; i++) suma += analogReadMilliVolts(PIN_POT);
  return suma / 16.0;
}

// ---------------- Conectividad ----------------
void conectarWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.printf("Conectando a WiFi %s", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
  Serial.printf("\nWiFi OK, IP %s\n", WiFi.localIP().toString().c_str());
}

void sincronizarHora() {             // TLS necesita la hora para validar certificados
  configTime(0, 0, "pool.ntp.org", "time.nist.gov");
  time_t ahora = time(nullptr);
  while (ahora < 1700000000) { delay(300); ahora = time(nullptr); }
  Serial.println("Hora sincronizada (NTP)");
}

void conectarMQTT() {
  while (!mqtt.connected()) {
    Serial.print("Conectando a AWS IoT Core... ");
    if (mqtt.connect(AWS_THING_NAME)) {
      Serial.println("OK");
    } else {
      Serial.printf("fallo, estado=%d. Reintento en 5 s\n", mqtt.state());
      delay(5000);
    }
  }
}

// ---------------- Comandos por el monitor serie ----------------
void leerComandos() {
  if (!Serial.available()) return;
  String c = Serial.readStringUntil('\n');
  c.trim();
  if (c == "d") {
    simularDrift = !simularDrift;
    Serial.println(simularDrift ? "Simulacion de drift ON (lectura x 0.90)" : "Simulacion de drift OFF");
  } else if (c == "t") {
    offsetActual = hx.read_average(20);
    Serial.printf("Nueva tara: offset=%ld\n", offsetActual);
  }
}

void setup() {
  Serial.begin(115200);
  delay(300);
  analogReadResolution(12);
  analogSetPinAttenuation(PIN_POT, ADC_11db);

  hx.begin(PIN_DT, PIN_SCK);

  conectarWiFi();
  sincronizarHora();
  red.setCACert(AWS_ROOT_CA);
  red.setCertificate(AWS_DEVICE_CERT);
  red.setPrivateKey(AWS_PRIVATE_KEY);
  mqtt.setServer(AWS_IOT_ENDPOINT, 8883);
  mqtt.setBufferSize(1024);           // el JSON supera los 256 bytes por defecto
  conectarMQTT();
  Serial.println("Comandos: d = simular drift, t = tara");
}

void loop() {
  leerComandos();
  conectarWiFi();
  if (!mqtt.connected()) conectarMQTT();
  mqtt.loop();

  if (!hx.is_ready()) return;          // el HX711 entrega ~10 muestras por segundo
  long raw = hx.read();

  // 1. Mediana
  ventana[idxVentana] = raw;
  idxVentana = (idxVentana + 1) % 5;
  if (idxVentana == 0) ventanaLlena = true;
  if (!ventanaLlena) return;
  long rawMed = mediana5(ventana);

  // 2. EMA
  if (!emaIniciada) { emaRaw = rawMed; emaIniciada = true; }
  emaRaw = EMA_ALFA * rawMed + (1.0 - EMA_ALFA) * emaRaw;

  if (millis() - ultimoEnvio < INTERVALO_ENVIO_MS) return;
  ultimoEnvio = millis();

  // 3. Calibracion (factor y offset salen de calibracion.py)
  double masaCruda = (raw - offsetActual) / CAL_FACTOR;
  double masaFilt  = (emaRaw - offsetActual) / CAL_FACTOR;
  if (simularDrift) { masaCruda *= 0.90; masaFilt *= 0.90; }

  // 4. Correccion del error sistematico (regresion medido = a * real + b)
  double masaReg = (masaFilt - REG_B) / REG_A;
  double mmSinCompensar = masaReg / G_POR_MM;   // para validar: antes de compensar el drift

  // Compensacion del drift
  double masaCorr = masaReg;
  if (simularDrift && CORREGIR_DRIFT) masaCorr /= 0.90;

  double mmCelda = masaCorr / G_POR_MM;
  double mmCruda = masaCruda / G_POR_MM;

  // Potenciometro: mm = K_POT * mV + C_POT (tambien sale de calibracion.py)
  double potMv = leerPotMv();
  double mmPot = K_POT * potMv + C_POT;

  // 5. Validacion
  String calidad = "OK";
  if (masaCorr < -MASA_TOLERANCIA_G || masaCorr > MASA_MAX_G ||
      fabs(masaCorr - masaAnterior) > SALTO_MAX_G) {
    calidad = "FUERA_RANGO";           // vaciado, golpe o falla
  }
  double ratio = NAN;
  if (mmPot > MM_MIN_VALIDACION) {
    // Se compara la lectura SIN compensar: si se usa la compensada, el drift nunca se detecta.
    ratio = mmSinCompensar / mmPot;
    if (calidad == "OK" && fabs(ratio - 1.0) > TOL_RATIO) calidad = "SOSPECHOSA";
  }
  masaAnterior = masaCorr;

  // Tasa de lluvia en mm/h entre dos envios
  unsigned long ahoraMs = millis();
  double tasa = 0;
  if (msAnteriorPub > 0) {
    double horas = (ahoraMs - msAnteriorPub) / 3600000.0;
    tasa = max(0.0, (mmCelda - mmAnteriorPub) / horas);
  }
  mmAnteriorPub = mmCelda;
  msAnteriorPub = ahoraMs;

  // Mensaje JSON (cada clave se vuelve una columna en DynamoDB)
  JsonDocument doc;
  doc["seq"] = ++secuencia;
  doc["epoch_s"] = (long)time(nullptr);
  doc["raw"] = raw;
  doc["masa_g"] = round(masaCorr * 10) / 10.0;
  doc["lluvia_cruda_mm"] = round(mmCruda * 100) / 100.0;
  doc["lluvia_mm"] = round(mmCelda * 100) / 100.0;
  doc["pot_mv"] = round(potMv);
  doc["lluvia_pot_mm"] = round(mmPot * 100) / 100.0;
  doc["tasa_mm_h"] = round(tasa * 100) / 100.0;
  if (!isnan(ratio)) doc["ratio"] = round(ratio * 1000) / 1000.0;
  doc["calidad"] = calidad;
  doc["drift_sim"] = simularDrift;

  char buf[512];
  size_t n = serializeJson(doc, buf);
  bool ok = mqtt.publish(AWS_TOPIC, buf, n);
  Serial.printf("%s %s\n", ok ? "Enviado" : "ERROR al enviar", buf);
}
