# -----------------------------------------------------------------------------
# AWS IoT Core: dispositivo, certificado X.509, politica y regla de ingesta
# Topico de telemetria: pluviometro/<thing_name>/telemetria
# -----------------------------------------------------------------------------

data "aws_caller_identity" "current" {}

data "aws_iot_endpoint" "ats" {
  endpoint_type = "iot:Data-ATS"
}

resource "aws_iot_thing" "esp32" {
  name = var.thing_name
}

# Certificado generado por AWS. La llave privada queda en el estado de Terraform
# (terraform.tfstate): ese archivo NO se sube al repositorio.
resource "aws_iot_certificate" "esp32" {
  active = true
}

resource "aws_iot_policy" "esp32" {
  name = "${var.project}-esp32-policy"

  # Minimo privilegio: solo se conecta con su propio client ID y publica en su propio topico.
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "iot:Connect"
        Resource = "arn:aws:iot:${var.aws_region}:${data.aws_caller_identity.current.account_id}:client/${var.thing_name}"
      },
      {
        Effect   = "Allow"
        Action   = "iot:Publish"
        Resource = "arn:aws:iot:${var.aws_region}:${data.aws_caller_identity.current.account_id}:topic/${var.project}/${var.thing_name}/*"
      }
    ]
  })
}

resource "aws_iot_policy_attachment" "esp32" {
  policy = aws_iot_policy.esp32.name
  target = aws_iot_certificate.esp32.arn
}

resource "aws_iot_thing_principal_attachment" "esp32" {
  thing     = aws_iot_thing.esp32.name
  principal = aws_iot_certificate.esp32.arn
}

# Regla: cada mensaje del ESP32 se guarda como un item en DynamoDB.
# topic(2) = nombre del dispositivo, timestamp() = hora de llegada en ms (UTC).
resource "aws_iot_topic_rule" "guardar_lecturas" {
  name        = "${var.project}_guardar_lecturas"
  description = "Guarda la telemetria del pluviometro en DynamoDB"
  enabled     = true
  sql_version = "2016-03-23"
  sql         = "SELECT *, topic(2) AS device_id, timestamp() AS ts FROM '${var.project}/+/telemetria'"

  dynamodbv2 {
    role_arn = local.iot_rule_role_arn
    put_item {
      table_name = aws_dynamodb_table.lecturas.name
    }
  }

  # Si la escritura falla, el error queda registrado en CloudWatch Logs.
  error_action {
    cloudwatch_logs {
      log_group_name = aws_cloudwatch_log_group.iot_errores.name
      role_arn       = local.iot_rule_role_arn
    }
  }
}

resource "aws_cloudwatch_log_group" "iot_errores" {
  name              = "/aws/iot/${var.project}-errores-regla"
  retention_in_days = 7
}

# Permiso de logs para el rol propio (LabRole ya lo tiene).
resource "aws_iam_role_policy" "iot_rule_logs" {
  count = var.use_lab_role ? 0 : 1
  name  = "logs-errores-regla"
  role  = aws_iam_role.iot_rule[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"]
      Resource = "${aws_cloudwatch_log_group.iot_errores.arn}:*"
    }]
  })
}
