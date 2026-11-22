# Demo opcional: firmware real en Wokwi publicando a AWS

1. Crea un proyecto ESP32 en wokwi.com y pega `diagram.json` de esta carpeta.
2. Agrega `libraries.txt` con tres líneas: `HX711`, `PubSubClient` y `ArduinoJson`.
3. Pega `firmware/pluviometro_mqtt/pluviometro_mqtt.ino` como `sketch.ino` y crea las pestañas
   `config.h` y `aws_secrets.h` (este último lo genera `terraform apply`).
4. En `config.h`: `INTERVALO_ENVIO_MS = 10000` para la demo y el `CAL_FACTOR` que obtengas
   en Wokwi con el sketch de calibración (`t`, luego `m 1000` con la celda en 1 kg).
5. Play. Sube la masa de la celda en pasos de menos de 200 g y mueve el potenciómetro en
   proporción (1 kg ≈ 50 mm de lluvia). Escribe `d` para simular el drift.

**Seguridad:** `aws_secrets.h` contiene la llave privada del dispositivo. No guardes el proyecto
de Wokwi como público. Al terminar, rota el certificado:
`terraform apply -replace=aws_iot_certificate.esp32`.
