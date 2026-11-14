# -----------------------------------------------------------------------------
# Genera el archivo de credenciales del ESP32 a partir de lo que creo Terraform.
# Queda en firmware/pluviometro_mqtt/aws_secrets.h (incluido en .gitignore).
# -----------------------------------------------------------------------------

data "http" "amazon_root_ca1" {
  count = var.generate_firmware_secrets ? 1 : 0
  url   = "https://www.amazontrust.com/repository/AmazonRootCA1.pem"
}

resource "local_sensitive_file" "aws_secrets_h" {
  count           = var.generate_firmware_secrets ? 1 : 0
  filename        = "${path.module}/../../firmware/pluviometro_mqtt/aws_secrets.h"
  file_permission = "0600"

  content = templatefile("${path.module}/templates/aws_secrets.h.tftpl", {
    endpoint    = data.aws_iot_endpoint.ats.endpoint_address
    thing_name  = var.thing_name
    topic       = "${var.project}/${var.thing_name}/telemetria"
    root_ca     = trimspace(data.http.amazon_root_ca1[0].response_body)
    device_cert = trimspace(aws_iot_certificate.esp32.certificate_pem)
    private_key = trimspace(aws_iot_certificate.esp32.private_key)
  })
}
