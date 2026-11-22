"""
Prueba de equivalencia firmware <-> gemelo digital (sin hardware).

Compila firmware/pluviometro_mqtt/pluviometro_mqtt.ino en el PC con g++, reemplazando
las librerias de Arduino por stubs (stubs_arduino.h): el HX711 "lee" la senal cruda que
genera el gemelo, el reloj avanza 100 ms por muestra y cada mqtt.publish se escribe en
la salida. Luego compara, publicacion por publicacion, lo que envia el firmware con lo
que calcula simulacion/gemelo_digital.py.

Uso: python verificar_firmware.py        (requiere g++, numpy y matplotlib)
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.path.join(AQUI, "..", ".."))
sys.path.insert(0, os.path.join(RAIZ, "simulacion"))
import gemelo_digital as g  # noqa: E402

FW = os.path.join(RAIZ, "firmware", "pluviometro_mqtt")


def main():
    mundo, cal = g.simular_mundo(), g.calibrar()
    gemelo, _ = g.procesar(mundo, cal)
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "raw.txt"), "w") as f:
            f.write("\n".join(str(int(x)) for x in mundo["raw"]))
        with open(os.path.join(tmp, "pot.txt"), "w") as f:
            f.write("\n".join(f"{x:.3f}" for x in mundo["pot_mv_limpio"]))
        # config.h con las constantes de la calibracion simulada
        cfg = open(os.path.join(FW, "config.h"), encoding="utf-8").read()
        for k, v in [("CAL_OFFSET", round(cal["offset"])), ("CAL_FACTOR", cal["factor"]),
                     ("REG_A", cal["a"]), ("REG_B", cal["b"]), ("K_POT", cal["k_pot"]), ("C_POT", cal["c_pot"])]:
            cfg = re.sub(r"(const \w+\s+%s\s*=\s*)[^;]+;" % k, r"\g<1>%r;" % v, cfg)
        open(os.path.join(tmp, "config.h"), "w").write(cfg)
        src = open(os.path.join(FW, "pluviometro_mqtt.ino"), encoding="utf-8").read()
        src = src.replace("#include <WiFi.h>", '#include "stubs_arduino.h"')
        src = re.sub(r'#include (<WiFiClientSecure.h>|<PubSubClient.h>|<ArduinoJson.h>|<time.h>|"HX711.h")\n', "", src)
        src = src.replace('#include "aws_secrets.h"', '#include "aws_secrets_falso.h"')
        src += """
#include <fstream>
int main() {
  std::ifstream a("raw.txt"), b("pot.txt"); long r; double p;
  while (a >> r) g_raw.push_back(r);
  while (b >> p) g_pot.push_back(p);
  setup();
  while (g_i < g_raw.size()) loop();
}
"""
        open(os.path.join(tmp, "fw.cpp"), "w").write(src)
        for h in ("stubs_arduino.h", "aws_secrets_falso.h"):
            open(os.path.join(tmp, h), "w").write(open(os.path.join(AQUI, h)).read())
        subprocess.run(["g++", "-std=c++17", "-O2", "fw.cpp", "-o", "fw"], cwd=tmp, check=True)
        salida = subprocess.run(["./fw"], cwd=tmp, check=True, capture_output=True, text=True).stdout
    firmware = [json.loads(l) for l in salida.splitlines() if l.startswith("{")]

    iguales = sum(f["calidad"] == t["calidad"] for f, t in zip(firmware, gemelo))
    dif = max(abs(f["lluvia_mm"] - t["lluvia_mm"]) for f, t in zip(firmware, gemelo))
    print(f"Publicaciones: firmware {len(firmware)}, gemelo {len(gemelo)}")
    print(f"Misma bandera de calidad: {iguales}/{len(gemelo)}")
    print(f"Diferencia maxima en lluvia_mm: {dif:.2f} mm (ruido del potenciometro en el gemelo)")
    print("Firmware:", dict(Counter(f["calidad"] for f in firmware)))
    print("Gemelo:  ", dict(Counter(t["calidad"] for t in gemelo)))
    ok = len(firmware) == len(gemelo) and iguales == len(gemelo) and dif < 0.5
    print("RESULTADO:", "EQUIVALENTES" if ok else "DIFERENCIAS")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
