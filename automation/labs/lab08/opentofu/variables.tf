variable "expected_account_id" {
  description = "Cuenta AWS autorizada y comprobada con STS antes de planificar."
  type        = string
  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "expected_account_id debe contener los 12 dígitos de la cuenta autorizada."
  }
}

variable "region" {
  description = "Región de AWS donde está el clúster."
  type        = string
  default     = "us-east-2"
}

variable "name" {
  description = "Prefijo de los recursos creados."
  type        = string
  default     = "rhcl-ext-svc"
}

variable "cluster_vpc_name" {
  description = "Etiqueta Name de la VPC del clúster; sus NAT Gateways son las IPs de salida del clúster."
  type        = string
  default     = "workshop-vpc"
}

variable "extra_allowed_cidrs" {
  description = "CIDRs adicionales que pueden llamar a la API externa (por ejemplo, tu IP para probar)."
  type        = list(string)
  default     = []
  validation {
    condition = alltrue([for cidr in var.extra_allowed_cidrs :
      try(cidrnetmask(cidr) != "0.0.0.0", false)
    ])
    error_message = "extra_allowed_cidrs admite solo CIDRs IPv4 válidos y no permite acceso global 0.0.0.0/0."
  }
}

variable "vpc_cidr" {
  description = "CIDR de la VPC aislada del servicio externo."
  type        = string
  default     = "10.50.0.0/16"
  validation {
    condition     = try(cidrnetmask(var.vpc_cidr) != "0.0.0.0" && tonumber(split("/", var.vpc_cidr)[1]) >= 16 && tonumber(split("/", var.vpc_cidr)[1]) <= 20, false)
    error_message = "vpc_cidr debe ser un CIDR IPv4 /16 a /20 para alojar la subred creada con cidrsubnet(..., 8, 1)."
  }
}

variable "instance_type" {
  description = "Tipo de instancia de la VM RHEL."
  type        = string
  default     = "t3.micro"
}

variable "api_port" {
  description = "Puerto en el que escucha la API externa."
  type        = number
  default     = 8080
}
