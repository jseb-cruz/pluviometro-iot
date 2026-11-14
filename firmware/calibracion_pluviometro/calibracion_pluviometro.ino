// Pluviometro gravimetrico IoT - prueba y calibracion
// ESP32 + HX711 (celda de carga) + potenciometro con flotador
// Comandos en el monitor serie:
//   h          ayuda
//   t          tara (recipiente vacio)
//   m 500      registra un punto con 500 g de referencia
//   s          activa o desactiva el modo continuo

#include "HX711.h"

const int PIN_DT  = 16;
const int PIN_SCK = 4;
const int PIN_POT = 34;      // ADC1: funciona con WiFi encendido
const int N_MUESTRAS = 30;   // a 10 SPS son unos 3 s por punto

HX711 hx;
long offsetRaw = 0;
bool modoContinuo = false;

// Promedio y desviacion estandar de n lecturas crudas del HX711
void leerCelda(int n, double &media, double &desv) {
  double suma = 0, suma2 = 0;
  for (int i = 0; i < n; i++) {
    while (!hx.is_ready()) delay(1);
    double v = (double)hx.read();
    suma += v;
    suma2 += v * v;
  }
  media = suma / n;
  double var = suma2 / n - media * media;
  desv = var > 0 ? sqrt(var) : 0;
}

// Promedio del potenciometro en milivoltios
double leerPot(int n) {
  long suma = 0;
  for (int i = 0; i < n; i++) {
    suma += analogReadMilliVolts(PIN_POT);
    delay(2);
  }
  return (double)suma / n;
}

void ayuda() {
  Serial.println("Comandos: h | t | m [gramos] | s");
  Serial.println("Ejemplo: m 500");
  Serial.println("Copia las lineas que empiezan con CAL, en datos_calibracion.csv");
}

void setup() {
  Serial.begin(115200);
  delay(500);
  analogReadResolution(12);
  analogSetPinAttenuation(PIN_POT, ADC_11db);
  hx.begin(PIN_DT, PIN_SCK);
  Serial.println("== Pluviometro gravimetrico: calibracion ==");
  if (!hx.wait_ready_timeout(2000)) {
    Serial.println("ERROR: el HX711 no responde. Revisa VCC, GND, DT y SCK.");
  }
  ayuda();
  Serial.println("CAL,ref_g,raw_media,raw_desv,pot_mv");
}

void loop() {
  if (Serial.available()) {
    String linea = Serial.readStringUntil('\n');
    linea.trim();

    if (linea == "h") {
      ayuda();
    } else if (linea == "t") {
      double media, desv;
      leerCelda(N_MUESTRAS, media, desv);
      offsetRaw = (long)media;
      Serial.printf("Tara lista. offset=%ld (desv=%.1f)\n", offsetRaw, desv);
    } else if (linea.startsWith("m")) {
      double ref = linea.substring(1).toFloat();
      Serial.printf("Midiendo %.1f g...\n", ref);
      double media, desv;
      leerCelda(N_MUESTRAS, media, desv);
      double pot = leerPot(50);
      Serial.printf("CAL,%.2f,%.1f,%.1f,%.1f\n", ref, media, desv, pot);
      if (ref > 0 && media - offsetRaw < 0) {
        Serial.println("AVISO: la lectura baja al cargar. Invierte A+ y A-.");
      }
    } else if (linea == "s") {
      modoContinuo = !modoContinuo;
      Serial.println(modoContinuo ? "Modo continuo ON" : "Modo continuo OFF");
    }
  }

  if (modoContinuo && hx.is_ready()) {
    long raw = hx.read();
    Serial.printf("neto:%ld pot_mv:%d\n", raw - offsetRaw, analogReadMilliVolts(PIN_POT));
  }
}
