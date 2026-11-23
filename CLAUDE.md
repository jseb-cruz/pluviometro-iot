# Pluviómetro gravimétrico IoT — contexto para Claude Code

Proyecto integrador de Juan Sebastian Cruz Gallo (Ingeniería de Datos e IA, USTA Tunja) para dos
materias: **Cloud Computing** y **Sistemas de Adquisición y Procesamiento de Datos**.
Entrega final: **26 de noviembre de 2026**. Responde siempre en español.

## Decisión de alcance
**No hay montaje físico.** El prototipo es simulado y así se declara en el informe:
- La adquisición se valida con el gemelo digital `simulacion/gemelo_digital.py`, que ejecuta el mismo
  algoritmo que `firmware/pluviometro_mqtt/pluviometro_mqtt.ino`.
- `simulacion/prueba_firmware/verificar_firmware.py` compila el firmware con g++ y debe dar
  "EQUIVALENTES" (180/180 publicaciones con la misma bandera de calidad).
- Si cambias la lógica del firmware, cambia también el gemelo y vuelve a correr ambos scripts.

## Tratamiento de la señal (firmware y gemelo)
1. Mediana de 5  2. EMA (α = 0,15)  3. Calibración  4. Regresión medido = a·real + b
5. Validación: FUERA_RANGO publica el último valor válido; desacuerdo si
   |mm_celda − mm_pot| > max(0,08·mm_pot, 0,8 mm) con más de 1 mm; si persiste 5 envíos se estima
   la ganancia (mediana de los cocientes) y se compensa. Calidades: OK, SOSPECHOSA, CORREGIDA, FUERA_RANGO.
6. Tasa: max(0, (masaReg − masaRegAnterior) / gananciaEst / G_POR_MM / horas), con la masa sin compensar
   y la misma ganancia en los dos envíos, para que activar la compensación no aparezca como lluvia
   (seq 141 del gemelo: 24,53 mm/h en vez de 165,07).

Resultados del gemelo (no inventar otros): RMSE 4,33 → 1,44 g; error máx. 104 → 8,4 g;
0 % falsas alarmas y 100 % de detección en 30 tormentas; detección a los 5 min;
error final −9,9 % → −0,4 %.

## Nube (AWS, cuenta propia, us-east-1, `use_lab_role = false`)
Terraform en `infra/terraform`: IoT Core (Thing + X.509), regla IoT → DynamoDB `pluviometro-lecturas`,
Lambda + API Gateway (`GET /lecturas`, parámetro `desde` incremental), S3 + CloudFront (OAC).
29 recursos. Mostrar siempre el plan antes de `terraform apply` y esperar confirmación.
Costos: `costos/estimacion_costos.py` (prototipo 0,94 USD/mes; demo 14,42 → 1,25 optimizada).

## Nunca subir a Git
`aws_secrets.h`, `terraform.tfstate*`, `tfplan`, `terraform.tfvars`, `build/` (ya en .gitignore).
No agregar atribución de Claude en los commits.

## Entregables
- Informe IEEE: `informe/informe.tex` → compilar con `pdflatex` dos veces desde `informe/`.
- Presentación de Cloud: está como artefacto en claude.ai (no en este repositorio).
- Presentación de Adquisición: pendiente.

## Pendiente
- [x] `terraform apply` para publicar el dashboard actualizado (CORREGIDA en ámbar)
- [x] `python simulacion/gemelo_digital.py --publicar` y capturas del dashboard con esos datos
- [ ] Presentación de Adquisición y procesamiento de datos
- [ ] Opcional: demo del firmware en Wokwi publicando a AWS (`simulacion/wokwi/DEMO_MQTT.md`)
