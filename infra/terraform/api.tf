# -----------------------------------------------------------------------------
# API de consulta: Lambda (Python) + API Gateway HTTP API
# GET /lecturas?device=<id>&horas=<n>
# -----------------------------------------------------------------------------

data "archive_file" "lambda_api" {
  type        = "zip"
  source_file = "${path.module}/../../lambda/api_lecturas.py"
  output_path = "${path.module}/build/api_lecturas.zip"
}

resource "aws_cloudwatch_log_group" "lambda_api" {
  name              = "/aws/lambda/${var.project}-api-lecturas"
  retention_in_days = 7
}

resource "aws_lambda_function" "api_lecturas" {
  function_name    = "${var.project}-api-lecturas"
  role             = local.lambda_role_arn
  runtime          = "python3.12"
  handler          = "api_lecturas.handler"
  filename         = data.archive_file.lambda_api.output_path
  source_code_hash = data.archive_file.lambda_api.output_base64sha256
  memory_size      = 128
  timeout          = 10

  environment {
    variables = {
      TABLE_NAME     = aws_dynamodb_table.lecturas.name
      DEFAULT_DEVICE = var.thing_name
      DEFAULT_HOURS  = tostring(var.api_default_hours)
    }
  }

  depends_on = [aws_cloudwatch_log_group.lambda_api]
}

resource "aws_apigatewayv2_api" "http" {
  name          = "${var.project}-api"
  protocol_type = "HTTP"

  cors_configuration {
    allow_origins = ["*"]
    allow_methods = ["GET", "OPTIONS"]
    allow_headers = ["content-type"]
    max_age       = 300
  }
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.http.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api_lecturas.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "get_lecturas" {
  api_id    = aws_apigatewayv2_api.http.id
  route_key = "GET /lecturas"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.http.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 20
    throttling_rate_limit  = 10
  }
}

resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowInvokeFromApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api_lecturas.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/*"
}
