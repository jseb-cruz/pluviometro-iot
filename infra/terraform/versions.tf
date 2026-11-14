terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.40"
    }
    archive = {
      source  = "hashicorp/archive"
      version = ">= 2.4"
    }
    local = {
      source  = "hashicorp/local"
      version = ">= 2.4"
    }
    http = {
      source  = "hashicorp/http"
      version = ">= 3.4"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Proyecto    = "pluviometro-gravimetrico-iot"
      Curso       = "Cloud Computing - USTA Tunja"
      Responsable = var.owner
      Gestionado  = "Terraform"
    }
  }
}
