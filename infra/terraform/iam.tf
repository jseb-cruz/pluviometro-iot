# -----------------------------------------------------------------------------
# Roles IAM
# En AWS Academy no se pueden crear roles: se reutiliza LabRole (use_lab_role = true).
# En una cuenta propia se crean dos roles de minimo privilegio.
# -----------------------------------------------------------------------------

data "aws_iam_role" "lab" {
  count = var.use_lab_role ? 1 : 0
  name  = var.lab_role_name
}

# --- Rol para que la regla de IoT escriba en DynamoDB ---
resource "aws_iam_role" "iot_rule" {
  count = var.use_lab_role ? 0 : 1
  name  = "${var.project}-iot-rule-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "iot.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "iot_rule" {
  count = var.use_lab_role ? 0 : 1
  name  = "put-item-lecturas"
  role  = aws_iam_role.iot_rule[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["dynamodb:PutItem"]
      Resource = aws_dynamodb_table.lecturas.arn
    }]
  })
}

# --- Rol de ejecucion de la Lambda (solo lectura de la tabla + logs) ---
resource "aws_iam_role" "lambda" {
  count = var.use_lab_role ? 0 : 1
  name  = "${var.project}-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_logs" {
  count      = var.use_lab_role ? 0 : 1
  role       = aws_iam_role.lambda[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "lambda_query" {
  count = var.use_lab_role ? 0 : 1
  name  = "query-lecturas"
  role  = aws_iam_role.lambda[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["dynamodb:Query"]
      Resource = aws_dynamodb_table.lecturas.arn
    }]
  })
}

locals {
  iot_rule_role_arn = var.use_lab_role ? data.aws_iam_role.lab[0].arn : aws_iam_role.iot_rule[0].arn
  lambda_role_arn   = var.use_lab_role ? data.aws_iam_role.lab[0].arn : aws_iam_role.lambda[0].arn
}
