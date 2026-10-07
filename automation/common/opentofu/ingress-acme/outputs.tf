output "dns_credentials" {
  description = "Credencial ACME exclusiva del clúster; nunca copiar a namespaces de participantes."
  sensitive   = true
  value = {
    AWS_ACCESS_KEY_ID     = module.dns_writer.access_key_id
    AWS_SECRET_ACCESS_KEY = module.dns_writer.secret_access_key
    AWS_REGION            = var.region
  }
}
output "zone_id" { value = data.aws_route53_zone.existing.zone_id }
output "iam_user_name" { value = module.dns_writer.iam_user_name }
output "challenge_name" { value = local.challenge_name }
