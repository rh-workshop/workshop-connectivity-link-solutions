variable "reviewed_configuration" {
  description = "Contrato revisado: cuenta, región, ARN NLB/TG HTTPS, UID Service, clúster y evidencia de auditoría IP/CCM. Nunca descubrir/adoptar otro TG automáticamente."
  type = object({
    account_id             = string
    region                 = string
    load_balancer_arn      = string
    target_group_arn       = string
    service_uid            = string
    cluster_id             = string
    ip_audit_approved      = bool
    ccm_ownership_verified = bool
  })
  validation {
    condition     = var.reviewed_configuration.ip_audit_approved && var.reviewed_configuration.ccm_ownership_verified
    error_message = "Revisa pérdida de IP original HTTPS y reconciliación CCM antes de planificar la excepción."
  }
}

variable "preserve_client_ip" {
  description = "false evita hairpin; true restaura el valor original. Solo cambia el marcador local, no crea ni importa el TG."
  type        = bool
  default     = false
}

variable "snapshot_path" {
  description = "Ruta absoluta privada NUEVA fuera de Git, para snapshot previo (0600). Usar otra ruta para rollback."
  type        = string
  validation {
    condition     = startswith(var.snapshot_path, "/")
    error_message = "snapshot_path debe ser absoluto y estar fuera del repositorio."
  }
}

variable "expected_current_preserve_client_ip" {
  description = "Baseline explícito revisado; si el atributo cambió, aborta antes de modificar."
  type        = bool
}

variable "approved_review_path" {
  description = "Informe verify-only privado revisado antes del plan."
  type        = string
}

variable "approved_review_sha256" {
  description = "SHA256 del informe privado revisado."
  type        = string
  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.approved_review_sha256))
    error_message = "Se requiere SHA256 exacto del artefacto revisado."
  }
}
