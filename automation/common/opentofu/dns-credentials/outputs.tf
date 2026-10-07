output "dns_credentials" {
  description = "Datos para el Secret kuadrant.io/aws y para ACME Route53; entregar sin imprimir y mediante vault."
  sensitive   = true
  value = {
    AWS_ACCESS_KEY_ID     = module.dns_writer.access_key_id
    AWS_SECRET_ACCESS_KEY = module.dns_writer.secret_access_key
    AWS_REGION            = var.region
  }
}

output "zone_id" {
  description = "Zona existente consultada; nunca se crea ni se elimina."
  value       = data.aws_route53_zone.existing.zone_id
}

output "record_patterns" {
  description = "Nombres autorizados para escritura en esta zona."
  value       = local.record_patterns
}

output "iam_user_name" {
  value = module.dns_writer.iam_user_name
}
