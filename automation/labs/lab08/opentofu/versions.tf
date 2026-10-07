terraform {
  required_version = ">= 1.6"

  # path y workspace_dir se configuran con rutas privadas fuera de Git al inicializar.
  backend "local" {}

  required_providers {
    aws = {
      # Mantener la identidad y los hashes del proveedor usado por los estados existentes.
      source  = "registry.terraform.io/hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# Las credenciales se leen de AWS_ACCESS_KEY_ID y AWS_SECRET_ACCESS_KEY.
provider "aws" {
  region              = var.region
  allowed_account_ids = [var.expected_account_id]

  default_tags {
    tags = {
      Project = "rhcl-escenarios-externos"
      Purpose = "backend-externo-connectivity-link"
    }
  }
}
