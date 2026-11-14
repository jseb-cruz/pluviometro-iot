variable "aws_region" {
  description = "Region de AWS. AWS Academy Learner Lab solo permite us-east-1 y us-west-2."
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Prefijo para nombrar los recursos."
  type        = string
  default     = "pluviometro"
}

variable "owner" {
  description = "Responsable del proyecto (etiqueta)."
  type        = string
  default     = "Juan Sebastian Cruz Gallo"
}

variable "thing_name" {
  description = "Nombre del dispositivo (Thing) en AWS IoT Core. Tambien es el client ID MQTT."
  type        = string
  default     = "pluviometro-esp32-01"
}

variable "use_lab_role" {
  description = <<-EOT
    true  -> usa el rol existente de AWS Academy (LabRole), porque el Learner Lab no permite crear roles IAM.
    false -> crea roles IAM de minimo privilegio (cuenta de AWS propia).
  EOT
  type        = bool
  default     = true
}

variable "lab_role_name" {
  description = "Nombre del rol preexistente en AWS Academy."
  type        = string
  default     = "LabRole"
}

variable "enable_cloudfront" {
  description = "Publica el dashboard con CloudFront (HTTPS). Si es false, solo se crea el bucket S3."
  type        = bool
  default     = true
}

variable "api_default_hours" {
  description = "Horas de historia que entrega la API si no se indica otra cosa."
  type        = number
  default     = 24
}

variable "generate_firmware_secrets" {
  description = "Genera firmware/pluviometro_mqtt/aws_secrets.h con el endpoint y los certificados."
  type        = bool
  default     = true
}
