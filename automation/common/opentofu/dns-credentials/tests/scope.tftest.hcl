# Pruebas locales con proveedor simulado: no usan credenciales ni APIs AWS.
mock_provider "aws" {
  mock_resource "aws_iam_policy" {
    defaults = {
      arn = "arn:aws:iam::000000000000:policy/rh-workshop/test-dns"
    }
  }
  mock_data "aws_route53_zone" {
    defaults = {
      zone_id = "ZEXAMPLE"
    }
  }
  mock_data "aws_partition" {
    defaults = {
      partition = "aws"
    }
  }
}

variables {
  expected_account_id = "000000000000"
  participant_id      = "user1"
  zone_name           = "example.com"
}

run "participant_and_acme_scope" {
  command = plan

  assert {
    condition     = jsondecode(module.dns_writer.policy_json).Statement[0].Resource == "arn:aws:route53:::hostedzone/ZEXAMPLE"
    error_message = "La escritura debe limitarse a la zona seleccionada."
  }
  assert {
    condition     = contains(output.record_patterns, "api-user1.cloud.example.com") && contains(output.record_patterns, "_acme-challenge.api-user1.cloud.example.com") && contains(output.record_patterns, "socios-user1.example.com") && contains(output.record_patterns, "b2b-user1.example.com")
    error_message = "Faltan los registros por participante o los desafíos ACME."
  }
  assert {
    condition     = !contains(jsondecode(module.dns_writer.policy_json).Statement[0].Condition["ForAllValues:StringEquals"]["route53:ChangeResourceRecordSetsRecordTypes"], "NS") && module.dns_writer.force_destroy == false
    error_message = "No se permite delegar la zona ni forzar la eliminación de recursos ajenos."
  }
}

run "reject_other_participant" {
  command = plan
  variables {
    record_patterns = ["api-user2.example.com"]
  }
  expect_failures = [data.aws_route53_zone.existing]
}

run "actual_lab_hosts_under_parent_zone" {
  command = plan
  variables {
    workshop_zone = "labs.example.com"
    cloud_zone    = "cloud.example.com"
  }
  assert {
    condition = alltrue([for host in ["api-user1.labs.example.com", "api-user1.cloud.example.com", "socios-user1.labs.example.com", "b2b-user1.labs.example.com"] :
      contains(output.record_patterns, host) && contains(output.record_patterns, "*.${host}") && contains(output.record_patterns, "_acme-challenge.${host}")
    ])
    error_message = "Cada hostname real de Labs 3, 7 y 11 debe incluir el registro, sus descendientes y el desafío ACME."
  }
  assert {
    condition     = !contains(output.record_patterns, "api-user1.example.com") && !contains(output.record_patterns, "api-user2.labs.example.com")
    error_message = "No deben añadirse hostnames fuera de la configuración o de otro participante."
  }
}

run "reject_external_workshop_zone" {
  command = plan
  variables {
    workshop_zone = "labs.other.example"
  }
  expect_failures = [data.aws_route53_zone.existing]
}

run "reject_external_cloud_zone" {
  command = plan
  variables {
    cloud_zone = "cloud.other.example"
  }
  expect_failures = [data.aws_route53_zone.existing]
}

run "reject_zone_wildcard" {
  command = plan
  variables {
    record_patterns = ["*.example.com"]
  }
  expect_failures = [data.aws_route53_zone.existing]
}

run "reject_other_zone" {
  command = plan
  variables {
    record_patterns = ["api-user1.other.example"]
  }
  expect_failures = [data.aws_route53_zone.existing]
}

run "reject_ambiguous_zone" {
  command = plan
  variables {
    zone_id = "ZEXAMPLE"
  }
  expect_failures = [data.aws_route53_zone.existing]
}

# El controlador real produjo CNAME api-user90... y TXT
# kuadrant-2jrg9qwx-cname-api-user90... en el mismo lote; dominio ficticio aquí.
run "kuadrant_mixed_traffic_and_ownership_batch" {
  command = plan
  variables {
    participant_id = "user90"
  }
  assert {
    condition = alltrue([for name in ["api-user90.example.com", "kuadrant-2jrg9qwx-cname-api-user90.example.com"] :
      anytrue([for pattern in jsondecode(module.dns_writer.policy_json).Statement[0].Condition["ForAllValues:StringLike"]["route53:ChangeResourceRecordSetsNormalizedRecordNames"] :
        can(regex("^${replace(replace(replace(pattern, ".", "\\."), "*", ".*"), "?", ".")}$", name))
      ])
    ]) && alltrue([for type in ["CNAME", "TXT"] : contains(jsondecode(module.dns_writer.policy_json).Statement[0].Condition["ForAllValues:StringEquals"]["route53:ChangeResourceRecordSetsRecordTypes"], type)])
    error_message = "El lote mixto de tráfico CNAME y propiedad TXT debe estar autorizado íntegro."
  }
  assert {
    condition = alltrue([for name in ["kuadrant-2jrg9qwx-cname-api-user91.example.com", "kuadrant-2jrg9qwx-cname-api-user90.other.example", "kuadrant-2jrg9qwxx-cname-api-user90.example.com", "kuadrant-2jrg9qwx-ns-api-user90.example.com", "kuadrant-active-groups.example.com"] :
      !anytrue([for pattern in jsondecode(module.dns_writer.policy_json).Statement[0].Condition["ForAllValues:StringLike"]["route53:ChangeResourceRecordSetsNormalizedRecordNames"] :
        can(regex("^${replace(replace(replace(pattern, ".", "\\."), "*", ".*"), "?", ".")}$", name))
      ])
    ])
    error_message = "La propiedad TXT no debe ampliar participante, zona, longitud del hash o tipos de endpoint."
  }
}

run "custom_scope_keeps_ownership_restricted" {
  command = plan
  variables {
    record_patterns = ["api-user1.example.com", "_acme-challenge.api-user1.example.com"]
  }
  assert {
    condition = (contains(jsondecode(module.dns_writer.policy_json).Statement[0].Condition["ForAllValues:StringLike"]["route53:ChangeResourceRecordSetsNormalizedRecordNames"], "kuadrant-????????-cname-api-user1.example.com") &&
      !contains(jsondecode(module.dns_writer.policy_json).Statement[0].Condition["ForAllValues:StringLike"]["route53:ChangeResourceRecordSetsNormalizedRecordNames"], "kuadrant-????????-cname-socios-user1.example.com") &&
    !contains(jsondecode(module.dns_writer.policy_json).Statement[0].Condition["ForAllValues:StringLike"]["route53:ChangeResourceRecordSetsNormalizedRecordNames"], "kuadrant-????????-cname-*.api-user1.example.com"))
    error_message = "Los patrones de propiedad deben conservar exactamente el alcance personalizado."
  }
}

run "managed_extension_preserves_legacy_inline" {
  command = plan
  assert {
    condition     = jsonencode(jsondecode(module.dns_writer.inline_policy_json).Statement[0].Condition["ForAllValues:StringLike"]["route53:ChangeResourceRecordSetsNormalizedRecordNames"]) == jsonencode(output.record_patterns)
    error_message = "La transición debe conservar exactamente los nombres de la política inline anterior."
  }
  assert {
    condition     = length(module.dns_writer.inline_policy_json) <= 2048 && length(module.dns_writer.policy_json) <= 6144
    error_message = "Ambas políticas deben cumplir los límites IAM."
  }
}
