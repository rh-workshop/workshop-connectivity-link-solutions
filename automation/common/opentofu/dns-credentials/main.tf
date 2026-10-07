data "aws_route53_zone" "existing" {
  name         = var.zone_name
  zone_id      = var.zone_id
  private_zone = false

  lifecycle {
    precondition {
      condition     = (var.zone_name == null) != (var.zone_id == null)
      error_message = "Define exactamente uno de zone_name o zone_id."
    }
    postcondition {
      condition     = alltrue([for zone in [var.workshop_zone, var.cloud_zone] : zone == null ? true : (trimsuffix(zone, ".") == trimsuffix(self.name, ".") || endswith(trimsuffix(zone, "."), ".${trimsuffix(self.name, ".")}"))]) && alltrue([for name in var.record_patterns : endswith(name, ".${trimsuffix(self.name, ".")}") && length(regexall("-${var.participant_id}\\.", name)) > 0])
      error_message = "Los dominios y patrones deben pertenecer a la zona seleccionada y a este participante."
    }
  }
}

locals {
  zone_name     = trimsuffix(data.aws_route53_zone.existing.name, ".")
  workshop_zone = var.workshop_zone == null ? local.zone_name : trimsuffix(var.workshop_zone, ".")
  cloud_zone    = var.cloud_zone == null ? "cloud.${local.zone_name}" : trimsuffix(var.cloud_zone, ".")
  hosts = [
    "api-${var.participant_id}.${local.workshop_zone}",
    "api-${var.participant_id}.${local.cloud_zone}",
    "socios-${var.participant_id}.${local.workshop_zone}",
    "b2b-${var.participant_id}.${local.workshop_zone}",
  ]
  default_patterns = flatten([for host in local.hosts : [host, "*.${host}", "_acme-challenge.${host}"]])
  record_patterns  = length(var.record_patterns) > 0 ? distinct(var.record_patterns) : local.default_patterns
  # Kuadrant registra propiedad con hash base36 de ocho caracteres y tipo.
  # Se deriva del alcance efectivo: una lista personalizada nunca recupera hosts excluidos.
  ownership_patterns = flatten([for host in local.record_patterns : [
    for type in ["a", "aaaa", "cname"] : "kuadrant-????????-${type}-${host}"
  ] if !startswith(host, "_acme-challenge.")])
}


module "dns_writer" {
  source      = "../modules/route53-writer"
  identity    = "rh-workshop-dns-${var.participant_id}-${lower(data.aws_route53_zone.existing.zone_id)}"
  purpose     = "participant-dns"
  policy_name = "participant-route53"
  zone_id     = data.aws_route53_zone.existing.zone_id
  # Route53 evalúa el lote mixto CNAME/TXT completo, no cada registro por separado.
  record_patterns         = local.record_patterns
  managed_policy          = true
  managed_record_patterns = distinct(concat(local.record_patterns, local.ownership_patterns))
  record_types            = ["A", "AAAA", "CNAME", "TXT"]
  tags                    = { Participant = var.participant_id }
}

moved {
  from = aws_iam_user.dns
  to   = module.dns_writer.aws_iam_user.dns
}
moved {
  from = aws_iam_user_policy.dns
  to   = module.dns_writer.aws_iam_user_policy.dns
}
moved {
  from = aws_iam_access_key.dns
  to   = module.dns_writer.aws_iam_access_key.dns
}
