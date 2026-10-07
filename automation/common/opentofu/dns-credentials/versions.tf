terraform {
  required_version = ">= 1.6"

  # Inicializar con path y workspace_dir absolutos fuera del repositorio.
  backend "local" {}

  required_providers {
    aws = {
      source  = "registry.terraform.io/hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region              = var.region
  allowed_account_ids = [var.expected_account_id]
}
