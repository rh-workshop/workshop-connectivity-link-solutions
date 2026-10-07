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

variable "participant_id" {
  description = "Participante propietario de estos registros; un estado y usuario IAM por participante."
  type        = string
  validation {
    condition     = can(regex("^[a-z0-9]([-a-z0-9]{0,30}[a-z0-9])?$", var.participant_id))
    error_message = "participant_id debe ser un nombre DNS de hasta 32 caracteres."
  }
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

variable "workshop_zone" {
  description = "Dominio de las APIs de Labs 3 y 11; puede ser una subzona de la zona alojada. Null usa la zona seleccionada."
  type        = string
  default     = null
  validation {
    condition     = var.workshop_zone == null ? true : can(regex("^[a-z0-9][a-z0-9.-]*[a-z0-9]\\.?$", var.workshop_zone))
    error_message = "workshop_zone debe ser un dominio en minúsculas."
  }
}

variable "cloud_zone" {
  description = "Dominio lab07_zona del Lab 7. Null usa cloud.<zona alojada>."
  type        = string
  default     = null
  validation {
    condition     = var.cloud_zone == null ? true : can(regex("^[a-z0-9][a-z0-9.-]*[a-z0-9]\\.?$", var.cloud_zone))
    error_message = "cloud_zone debe ser un dominio en minúsculas."
  }
}

variable "record_patterns" {
  description = "Patrones IAM de nombres normalizados del participante. Vacío genera api/cloud/socios/b2b, sus descendientes y desafíos ACME."
  type        = list(string)
  default     = []
  validation {
    condition = alltrue([for name in var.record_patterns :
      can(regex("^[a-z0-9_.*-]+$", name)) && !endswith(name, ".")
    ])
    error_message = "Los patrones deben estar en minúsculas y sin punto final; solo DNS, _ y comodín IAM *."
  }
}
