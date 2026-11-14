// Configuracion del pluviometro. Ajusta estos valores con tus datos.
#pragma once

// ---- WiFi (en Wokwi usa "Wokwi-GUEST" y clave vacia) ----
#define WIFI_SSID "Wokwi-GUEST"
#define WIFI_PASS ""

// ---- Pines ----
const int PIN_DT  = 16;
const int PIN_SCK = 4;
const int PIN_POT = 34;

// ---- Geometria: embudo de 160 mm -> A = 0.0201 m2 -> 1 mm = 20.1 g ----
const double G_POR_MM = 20.106;

// ---- Calibracion de la celda (salen de calibracion.py, seccion 1) ----
const long   CAL_OFFSET = 0;        // cuentas con el recipiente vacio
const double CAL_FACTOR = 420.0;    // cuentas por gramo (valor provisional)

// ---- Correccion del error sistematico (calibracion.py, seccion 2) ----
const double REG_A = 1.0;           // ganancia: medido = a * real + b
const double REG_B = 0.0;           // offset en gramos
const bool   CORREGIR_DRIFT = true; // en la demo de drift: true = se compensa

// ---- Potenciometro (calibracion.py, seccion 3): mm = K_POT * mV + C_POT ----
const double K_POT = 0.05;
const double C_POT = -15.0;

// ---- Filtros y validacion ----
const double EMA_ALFA = 0.15;            // entre 0.1 y 0.2
const double MASA_MAX_G = 2000;          // capacidad util del recipiente (~100 mm)
const double MASA_TOLERANCIA_G = 30;     // lluvia negativa tolerada antes de marcar
const double SALTO_MAX_G = 200;          // ~10 mm en un intervalo: imposible
const double TOL_RATIO = 0.08;           // +-8 %: debe ser menor que el drift a detectar (10 %)
const double MM_MIN_VALIDACION = 1.0;    // por debajo de 1 mm no se compara

// ---- Envio ----
const unsigned long INTERVALO_ENVIO_MS = 60000;   // 1 mensaje por minuto (10000 para demos)
