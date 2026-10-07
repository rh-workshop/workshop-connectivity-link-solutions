variable "expected_account_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "expected_account_id debe ser la cuenta autorizada de 12 dígitos."
  }
}

variable "region" {
  type    = string
  default = "us-east-2"
}

variable "vpc_id" {
  description = "VPC existente del clúster autorizado."
  type        = string
  validation {
    condition     = can(regex("^vpc-[a-z0-9]+$", var.vpc_id))
    error_message = "vpc_id debe identificar una VPC existente."
  }
}

variable "expected_cluster_id" {
  description = "InfrastructureName del clúster; debe haber instancias running etiquetadas para él dentro de la VPC."
  type        = string
  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]+$", var.expected_cluster_id))
    error_message = "expected_cluster_id debe ser el InfrastructureName verificado."
  }
}

variable "subnet_ids" {
  description = "IDs explícitos de subredes públicas existentes, una por AZ."
  type        = list(string)
  validation {
    condition     = length(var.subnet_ids) > 0 && length(distinct(var.subnet_ids)) == length(var.subnet_ids) && alltrue([for id in var.subnet_ids : can(regex("^subnet-[a-z0-9]+$", id))])
    error_message = "subnet_ids debe contener IDs válidos únicos y no puede estar vacío."
  }
}

variable "minimum_available_ips" {
  description = "Capacidad libre mínima por subred; nunca inferior a ocho direcciones."
  type        = number
  default     = 8
  validation {
    condition     = var.minimum_available_ips >= 8 && floor(var.minimum_available_ips) == var.minimum_available_ips
    error_message = "minimum_available_ips debe ser un entero de al menos 8."
  }
}
