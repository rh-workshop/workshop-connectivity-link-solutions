output "api_public_ip" {
  description = "IP pública de la API externa."
  value       = aws_instance.api.public_ip
}

output "api_public_dns" {
  description = "Nombre DNS público de la API externa (úsalo en el ServiceEntry)."
  value       = aws_instance.api.public_dns
}

output "api_url" {
  description = "URL directa de la API, solo accesible desde los CIDRs permitidos."
  value       = "http://${aws_instance.api.public_dns}:${var.api_port}/v1/items"
}

output "allowed_cidrs" {
  description = "Orígenes autorizados en el grupo de seguridad."
  value       = local.allowed_cidrs
}
