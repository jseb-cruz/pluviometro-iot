"""
API de consulta del pluviometro gravimetrico IoT.

GET /lecturas?device=<id>&horas=<n>[&desde=<ts_ms>]
Devuelve las lecturas de las ultimas n horas (max. 168), ordenadas en el tiempo.
Con "desde" solo devuelve las lecturas posteriores a ese instante (consulta incremental:
el dashboard pide solo lo nuevo y asi se reducen las lecturas de DynamoDB).
Se despliega con Terraform (infra/terraform/api.tf) detras de un API Gateway HTTP API.
"""
import json
import os
import time
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

TABLE = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
DEFAULT_DEVICE = os.environ.get("DEFAULT_DEVICE", "pluviometro-esp32-01")
DEFAULT_HOURS = int(os.environ.get("DEFAULT_HOURS", "24"))
MAX_HOURS = 168
MAX_ITEMS = 5000

HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Cache-Control": "no-store",
}


def _a_json(valor):
    """DynamoDB devuelve Decimal: se convierte a int o float para JSON."""
    if isinstance(valor, Decimal):
        return int(valor) if valor == valor.to_integral_value() else float(valor)
    raise TypeError(f"Tipo no serializable: {type(valor)}")


def _respuesta(codigo, cuerpo):
    return {"statusCode": codigo, "headers": HEADERS,
            "body": json.dumps(cuerpo, default=_a_json)}


def handler(event, context):
    params = event.get("queryStringParameters") or {}
    device = params.get("device", DEFAULT_DEVICE)

    try:
        horas = float(params.get("horas", DEFAULT_HOURS))
    except ValueError:
        return _respuesta(400, {"error": "El parametro 'horas' debe ser numerico"})
    horas = max(0.1, min(horas, MAX_HOURS))

    desde_ms = int((time.time() - horas * 3600) * 1000)
    if params.get("desde"):
        try:
            desde_ms = max(desde_ms, int(params["desde"]) + 1)
        except ValueError:
            return _respuesta(400, {"error": "El parametro 'desde' debe ser un entero (ms)"})

    consulta = {
        "KeyConditionExpression": Key("device_id").eq(device) & Key("ts").gte(desde_ms),
        "ScanIndexForward": True,
    }

    items = []
    while True:
        pagina = TABLE.query(**consulta)
        items.extend(pagina.get("Items", []))
        clave = pagina.get("LastEvaluatedKey")
        if not clave or len(items) >= MAX_ITEMS:
            break
        consulta["ExclusiveStartKey"] = clave

    return _respuesta(200, {
        "device": device,
        "horas": horas,
        "n": len(items),
        "lecturas": items[-MAX_ITEMS:],
    })
