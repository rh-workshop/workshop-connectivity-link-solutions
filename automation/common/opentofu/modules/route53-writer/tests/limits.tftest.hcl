mock_provider "aws" {
  mock_resource "aws_iam_policy" {
    defaults = { arn = "arn:aws:iam::000000000000:policy/rh-workshop/test-dns" }
  }
  mock_data "aws_partition" {
    defaults = { partition = "aws" }
  }
}
variables {
  identity        = "rh-workshop-dns-user1-zexample"
  purpose         = "participant-dns"
  policy_name     = "participant-route53"
  zone_id         = "ZEXAMPLE"
  record_patterns = ["api-user1.example.com"]
  record_types    = ["CNAME", "TXT"]
  tags            = { Participant = "user1" }
}
run "reject_oversized_inline" {
  command = plan
  variables {
    record_patterns = [for i in range(100) : "host-${i}.api-user1.example.com"]
  }
  expect_failures = [aws_iam_user_policy.dns]
}
run "reject_oversized_managed" {
  command = plan
  variables {
    managed_policy          = true
    managed_record_patterns = [for i in range(500) : "kuadrant-????????-cname-host-${i}.api-user1.example.com"]
  }
  expect_failures = [aws_iam_policy.dns]
}
run "legacy_inline_stays_unmanaged" {
  command = plan
  assert {
    condition     = length(aws_iam_policy.dns) == 0 && length(aws_iam_user_policy_attachment.dns) == 0
    error_message = "Los consumidores existentes no deben recibir políticas administradas por defecto."
  }
}
