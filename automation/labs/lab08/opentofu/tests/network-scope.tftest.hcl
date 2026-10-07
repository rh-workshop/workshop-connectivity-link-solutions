mock_provider "aws" {
  mock_data "aws_vpc" {
    defaults = { id = "vpc-test" }
  }
  mock_data "aws_nat_gateways" {
    defaults = { ids = ["nat-test"] }
  }
  mock_data "aws_nat_gateway" {
    defaults = { public_ip = "203.0.113.20" }
  }
  mock_data "aws_ami" {
    defaults = { id = "ami-test" }
  }
  mock_data "aws_availability_zones" {
    defaults = { names = ["us-east-2a"] }
  }
}

variables {
  expected_account_id = "000000000000"
}

run "nat_addresses_are_restricted" {
  command = plan
  assert {
    condition     = output.allowed_cidrs == ["203.0.113.20/32"]
    error_message = "La API solo debe admitir las IPs NAT del clúster."
  }
}

run "empty_nat_requires_explicit_cidrs" {
  command = plan
  override_data {
    target = data.aws_nat_gateways.cluster
    values = { ids = [] }
  }
  expect_failures = [aws_security_group.ext]
}

run "explicit_egress_without_nat" {
  command = plan
  variables {
    extra_allowed_cidrs = ["203.0.113.10/32"]
  }
  override_data {
    target = data.aws_nat_gateways.cluster
    values = { ids = [] }
  }
  assert {
    condition     = output.allowed_cidrs == ["203.0.113.10/32"]
    error_message = "Sin NAT solo deben admitirse los CIDRs explícitos."
  }
}

run "reject_global_ingress" {
  command = plan
  variables {
    extra_allowed_cidrs = ["0.0.0.0/0"]
  }
  expect_failures = [var.extra_allowed_cidrs]
}

run "reject_ipv6_ingress" {
  command = plan
  variables {
    extra_allowed_cidrs = ["2001:db8::/64"]
  }
  expect_failures = [var.extra_allowed_cidrs]
}

run "reject_invalid_ingress" {
  command = plan
  variables {
    extra_allowed_cidrs = ["not-a-cidr"]
  }
  expect_failures = [var.extra_allowed_cidrs]
}

run "reject_invalid_account" {
  command = plan
  variables {
    expected_account_id = "123"
  }
  expect_failures = [var.expected_account_id]
}
