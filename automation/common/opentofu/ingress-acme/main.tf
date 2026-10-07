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
      condition     = var.ingress_domain == trimsuffix(self.name, ".") || endswith(var.ingress_domain, ".${trimsuffix(self.name, ".")}")
      error_message = "El dominio Ingress debe pertenecer a la zona pública seleccionada."
    }
  }
}

locals {
  challenge_name = "_acme-challenge.${var.ingress_domain}"
}

module "dns_writer" {
  source          = "../modules/route53-writer"
  identity        = "rh-workshop-ingress-acme-${lower(data.aws_route53_zone.existing.zone_id)}-${substr(sha256(var.ingress_domain), 0, 8)}"
  purpose         = "cluster-ingress-acme"
  policy_name     = "ingress-acme-route53"
  zone_id         = data.aws_route53_zone.existing.zone_id
  record_patterns = [local.challenge_name]
  record_types    = ["TXT"]
  tags            = { IngressDomain = var.ingress_domain }
}
