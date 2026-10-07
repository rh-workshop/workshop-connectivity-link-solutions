variable "expected_account_id" {
  description = "Cuenta AWS verificada por el instructor antes de planificar."
  type        = string
  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "expected_account_id debe contener los 12 dígitos de la cuenta autorizada."
  }
}

variable "region" {
  description = "Región para el proveedor AWS; Route 53 e IAM son servicios globales."
  type        = string
  default     = "us-east-2"
}

variable "zone_name" {
  description = "Nombre de la zona pública existente. Usa zone_name o zone_id, no ambos."
  type        = string
  default     = null
  nullable    = true
  validation {
    condition     = var.zone_name == null ? true : can(regex("^[a-z0-9][a-z0-9.-]*[a-z0-9]\\.?$", var.zone_name))
    error_message = "zone_name debe ser un dominio en minúsculas."
  }
}

variable "zone_id" {
  description = "ID de la zona pública existente, sin /hostedzone/."
  type        = string
  default     = null
  nullable    = true
  validation {
    condition     = var.zone_id == null ? true : can(regex("^Z[A-Z0-9]+$", var.zone_id))
    error_message = "zone_id debe comenzar con Z y no incluir /hostedzone/."
  }
}

variable "ingress_domain" {
  description = "Dominio exacto leído del Ingress cluster de OpenShift; sin wildcard ni protocolo."
  type        = string
  validation {
    condition     = can(regex("^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$", var.ingress_domain))
    error_message = "ingress_domain debe ser el dominio explícito normalizado del Ingress, sin wildcard."
  }
}
