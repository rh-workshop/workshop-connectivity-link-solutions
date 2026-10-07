mock_provider "aws" {
  mock_data "aws_route53_zone" { defaults = { zone_id = "ZEXAMPLE" } }
  mock_data "aws_partition" { defaults = { partition = "aws" } }
}
variables {
  expected_account_id = "000000000000"
  zone_name           = "example.com"
  ingress_domain      = "apps.example.com"
}
run "exact_ingress_txt_only" {
  command = plan
  assert {
    condition     = jsondecode(module.dns_writer.policy_json).Statement[0].Condition["ForAllValues:StringLike"]["route53:ChangeResourceRecordSetsNormalizedRecordNames"] == ["_acme-challenge.apps.example.com"]
    error_message = "La credencial Ingress solo puede escribir el desafío exacto del dominio declarado."
  }
  assert {
    condition     = jsondecode(module.dns_writer.policy_json).Statement[0].Condition["ForAllValues:StringEquals"]["route53:ChangeResourceRecordSetsRecordTypes"] == ["TXT"]
    error_message = "La credencial ACME no debe escribir A, AAAA, CNAME, NS ni SOA."
  }
  assert {
    condition     = jsondecode(module.dns_writer.policy_json).Statement[0].Resource == "arn:aws:route53:::hostedzone/ZEXAMPLE" && module.dns_writer.force_destroy == false
    error_message = "La escritura debe estar limitada a una zona y el usuario no debe permitir force_destroy."
  }
}
run "reject_ingress_outside_zone" {
  command = plan
  variables { ingress_domain = "apps.other.example" }
  expect_failures = [data.aws_route53_zone.existing]
}
run "reject_ingress_wildcard" {
  command = plan
  variables { ingress_domain = "*.apps.example.com" }
  expect_failures = [var.ingress_domain]
}
run "reject_ambiguous_zone" {
  command = plan
  variables { zone_id = "ZEXAMPLE" }
  expect_failures = [data.aws_route53_zone.existing]
}
