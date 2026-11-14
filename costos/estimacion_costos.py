"""
Estimacion preliminar de costos mensuales - Pluviometro gravimetrico IoT (AWS us-east-1)

Precios de lista bajo demanda, SIN capa gratuita (escenario conservador).
Fuentes: paginas de precios de AWS IoT Core, DynamoDB, Lambda, API Gateway,
S3 y CloudFront (consultadas el 14 de noviembre de 2026).

Uso: python estimacion_costos.py   -> imprime la tabla y genera costos.csv
"""
import csv
import math

# ---------------- Precios (USD) ----------------
P = {
    "iot_conectividad_por_millon_min": 0.08,
    "iot_mensajes_por_millon": 1.00,          # mensajes medidos en bloques de 5 KB
    "iot_reglas_por_millon": 0.15,
    "iot_acciones_por_millon": 0.15,
    "ddb_wru_por_millon": 0.625,              # escritura de hasta 1 KB
    "ddb_rru_por_millon": 0.125,              # lectura de hasta 4 KB (consistente fuerte)
    "ddb_gb_mes": 0.25,
    "lambda_por_millon": 0.20,
    "lambda_gb_s": 0.0000166667,
    "apigw_http_por_millon": 1.00,
    "s3_gb_mes": 0.023,
    "s3_get_por_mil": 0.0004,
    "cf_gb": 0.085,
    "cf_https_por_10mil": 0.01,
    "logs_gb_ingesta": 0.50,
}

MIN_MES = 30 * 24 * 60
ITEM_BYTES = 350            # tamano tipico de una lectura en DynamoDB


def escenario(nombre, dispositivos, intervalo_s, horas_dashboard_dia, usuarios, incremental=False):
    msgs = dispositivos * MIN_MES * 60 / intervalo_s
    # Dashboard: una consulta cada 30 s mientras esta abierto, 24 h de datos por consulta
    consultas = usuarios * 30 * horas_dashboard_dia * 120
    items_24h = 24 * 3600 / intervalo_s
    rru_por_consulta = math.ceil(items_24h * ITEM_BYTES / 4096) * 0.5  # eventualmente consistente
    if incremental:
        # Una carga completa por sesion (~1 por hora abierta) y el resto solo trae lo nuevo (<4 KB)
        cargas_completas = usuarios * 30 * horas_dashboard_dia
        rru_total = cargas_completas * rru_por_consulta + (consultas - cargas_completas) * 0.5
        rru_por_consulta = rru_total / consultas
    gb_tabla = msgs * ITEM_BYTES / 1e9  # crecimiento en el primer mes
    cargas_pagina = usuarios * 30 * 3
    gb_cf = cargas_pagina * 0.25e6 / 1e9   # ~250 KB por carga de pagina; la API no pasa por CloudFront

    c = {
        "IoT Core (conectividad)": dispositivos * MIN_MES / 1e6 * P["iot_conectividad_por_millon_min"],
        "IoT Core (mensajes)": msgs / 1e6 * P["iot_mensajes_por_millon"],
        "IoT Core (regla + accion)": msgs / 1e6 * (P["iot_reglas_por_millon"] + P["iot_acciones_por_millon"]),
        "DynamoDB (escrituras)": msgs / 1e6 * P["ddb_wru_por_millon"],
        "DynamoDB (lecturas)": consultas * rru_por_consulta / 1e6 * P["ddb_rru_por_millon"],
        "DynamoDB (almacenamiento)": gb_tabla * P["ddb_gb_mes"],
        "Lambda": consultas / 1e6 * P["lambda_por_millon"] + consultas * 0.128 * 0.3 * P["lambda_gb_s"],
        "API Gateway (HTTP API)": consultas / 1e6 * P["apigw_http_por_millon"],
        "S3 + CloudFront": 0.001 * P["s3_gb_mes"] + cargas_pagina * 2 / 1000 * P["s3_get_por_mil"]
                           + gb_cf * P["cf_gb"] + cargas_pagina * 2 / 1e4 * P["cf_https_por_10mil"],
        "CloudWatch Logs": consultas * 300 / 1e9 * P["logs_gb_ingesta"],   # ~300 B de log por invocacion
    }
    return nombre, msgs, consultas, c


ESCENARIOS = [
    escenario("Prototipo", 1, 60, 8, 3),
    escenario("Demostracion", 1, 10, 8, 10),
    escenario("Demostracion optimizada", 1, 10, 8, 10, incremental=True),
    escenario("Red regional optimizada", 50, 60, 24, 50, incremental=True),
]
# Prototipo: 1 estacion, 1 msg/min, 3 usuarios 8 h/dia, recarga completa cada 30 s
# Demostracion: 1 estacion, 1 msg/10 s, 10 usuarios 8 h/dia, recarga completa
# Demostracion optimizada: igual, pero el dashboard pide solo lecturas nuevas
# Red regional optimizada: 50 estaciones, 1 msg/min, 50 usuarios 24 h/dia, incremental


def main():
    conceptos = list(ESCENARIOS[0][3].keys())
    ancho = max(len(c) for c in conceptos) + 2
    print(f"{'Concepto':<{ancho}}" + "".join(f"{e[0][:24]:>25}" for e in ESCENARIOS))
    for k in conceptos:
        print(f"{k:<{ancho}}" + "".join(f"{e[3][k]:>25.4f}" for e in ESCENARIOS))
    totales = [sum(e[3].values()) for e in ESCENARIOS]
    print(f"{'TOTAL USD / mes':<{ancho}}" + "".join(f"{t:>25.2f}" for t in totales))
    for nombre, msgs, consultas, _ in ESCENARIOS:
        print(f"  {nombre}: {msgs:,.0f} mensajes/mes, {consultas:,.0f} consultas/mes")

    with open("costos.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["concepto"] + [e[0] for e in ESCENARIOS])
        for k in conceptos:
            w.writerow([k] + [round(e[3][k], 4) for e in ESCENARIOS])
        w.writerow(["TOTAL"] + [round(t, 2) for t in totales])
    print("\nTabla guardada en costos.csv")


if __name__ == "__main__":
    main()
