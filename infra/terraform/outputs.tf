output "iot_endpoint" {
  description = "Endpoint MQTT (puerto 8883) al que se conecta el ESP32."
  value       = data.aws_iot_endpoint.ats.endpoint_address
}

output "mqtt_topic" {
  description = "Topico donde publica el ESP32."
  value       = "${var.project}/${var.thing_name}/telemetria"
}

output "dynamodb_table" {
  value = aws_dynamodb_table.lecturas.name
}

output "api_url" {
  description = "Endpoint de consulta del dashboard."
  value       = "${trimsuffix(aws_apigatewayv2_stage.default.invoke_url, "/")}/lecturas"
}

output "dashboard_url" {
  description = "URL publica del dashboard."
  value       = var.enable_cloudfront ? "https://${aws_cloudfront_distribution.dashboard[0].domain_name}" : "Sin CloudFront: bucket ${aws_s3_bucket.dashboard.bucket}"
}

output "certificate_id" {
  value = aws_iot_certificate.esp32.id
}
