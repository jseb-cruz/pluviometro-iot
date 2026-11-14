# -----------------------------------------------------------------------------
# Almacenamiento: DynamoDB (series de tiempo por dispositivo)
# Clave de particion: device_id   Clave de ordenamiento: ts (epoch en ms)
# -----------------------------------------------------------------------------

resource "aws_dynamodb_table" "lecturas" {
  name         = "${var.project}-lecturas"
  billing_mode = "PAY_PER_REQUEST" # bajo demanda: solo se paga lo que se usa

  hash_key  = "device_id"
  range_key = "ts"

  attribute {
    name = "device_id"
    type = "S"
  }

  attribute {
    name = "ts"
    type = "N"
  }

  point_in_time_recovery {
    enabled = false # se activa en produccion; en el prototipo agrega costo
  }
}
