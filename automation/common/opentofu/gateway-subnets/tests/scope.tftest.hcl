mock_provider "aws" {
  mock_data "aws_instances" {
    defaults = { ids = ["i-example"] }
  }
  mock_data "aws_internet_gateway" {
    defaults = { id = "igw-example" }
  }
  mock_data "aws_subnet" {
    defaults = {
      vpc_id                     = "vpc-example"
      available_ip_address_count = 4090
    }
  }
  mock_data "aws_route_table" {
    defaults = {
      vpc_id = "vpc-example"
      routes = [{ cidr_block = "0.0.0.0/0", gateway_id = "igw-example", carrier_gateway_id = "", core_network_arn = "", destination_prefix_list_id = "", egress_only_gateway_id = "", instance_id = "", ipv6_cidr_block = "", local_gateway_id = "", nat_gateway_id = "", network_interface_id = "", transit_gateway_id = "", vpc_endpoint_id = "", vpc_peering_connection_id = "" }]
    }
  }
}

variables {
  expected_account_id = "000000000000"
  expected_cluster_id = "workshop-example"
  vpc_id              = "vpc-example"
  subnet_ids          = ["subnet-a", "subnet-b", "subnet-c"]
}

override_data {
  target = data.aws_subnet.selected["subnet-a"]
  values = { availability_zone = "us-east-2a", vpc_id = "vpc-example", available_ip_address_count = 4090 }
}
override_data {
  target = data.aws_subnet.selected["subnet-b"]
  values = { availability_zone = "us-east-2b", vpc_id = "vpc-example", available_ip_address_count = 4090 }
}
override_data {
  target = data.aws_subnet.selected["subnet-c"]
  values = { availability_zone = "us-east-2c", vpc_id = "vpc-example", available_ip_address_count = 4090 }
}

run "existing_public_subnets" {
  command = plan
  assert {
    condition     = output.aws_load_balancer_subnet_ids == tolist(["subnet-a", "subnet-b", "subnet-c"]) && output.aws_load_balancer_subnets == "subnet-a,subnet-b,subnet-c"
    error_message = "Las salidas deben conservar la lista y la anotación explícita."
  }
}

run "reject_other_vpc" {
  command = plan
  override_data {
    target = data.aws_subnet.selected["subnet-a"]
    values = { vpc_id = "vpc-other", availability_zone = "us-east-2a", available_ip_address_count = 4090 }
  }
  expect_failures = [data.aws_subnet.selected]
}

run "reject_private_route" {
  command = plan
  override_data {
    target = data.aws_route_table.public["subnet-a"]
    values = {
      vpc_id = "vpc-example"
      routes = [{ cidr_block = "0.0.0.0/0", nat_gateway_id = "nat-example", gateway_id = "", carrier_gateway_id = "", core_network_arn = "", destination_prefix_list_id = "", egress_only_gateway_id = "", instance_id = "", ipv6_cidr_block = "", local_gateway_id = "", network_interface_id = "", transit_gateway_id = "", vpc_endpoint_id = "", vpc_peering_connection_id = "" }]
    }
  }
  expect_failures = [data.aws_route_table.public]
}

run "reject_missing_igw" {
  command = plan
  override_data {
    target = data.aws_internet_gateway.existing
    values = { id = "" }
  }
  expect_failures = [data.aws_internet_gateway.existing]
}

run "reject_duplicate_az" {
  command = plan
  override_data {
    target = data.aws_subnet.selected["subnet-b"]
    values = { availability_zone = "us-east-2a", vpc_id = "vpc-example", available_ip_address_count = 4090 }
  }
  expect_failures = [data.aws_route_table.public]
}

run "reject_low_capacity" {
  command = plan
  override_data {
    target = data.aws_subnet.selected["subnet-a"]
    values = { available_ip_address_count = 7, availability_zone = "us-east-2a", vpc_id = "vpc-example" }
  }
  expect_failures = [data.aws_subnet.selected]
}

run "reject_wrong_cluster" {
  command = plan
  override_data {
    target = data.aws_instances.cluster
    values = { ids = [] }
  }
  expect_failures = [data.aws_instances.cluster]
}

run "reject_duplicate_ids" {
  command = plan
  variables {
    subnet_ids = ["subnet-a", "subnet-a"]
  }
  expect_failures = [var.subnet_ids]
}
