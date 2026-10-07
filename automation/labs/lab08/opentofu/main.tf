# IPs de salida del clúster: las únicas, junto con extra_allowed_cidrs, que llegan a la API.
data "aws_vpc" "cluster" {
  filter {
    name   = "tag:Name"
    values = [var.cluster_vpc_name]
  }
}

data "aws_nat_gateways" "cluster" {
  vpc_id = data.aws_vpc.cluster.id

  filter {
    name   = "state"
    values = ["available"]
  }
}

data "aws_nat_gateway" "cluster" {
  for_each = toset(data.aws_nat_gateways.cluster.ids)
  id       = each.value
}

data "aws_ami" "rhel9" {
  most_recent = true
  owners      = ["309956199498"] # Red Hat

  filter {
    name   = "name"
    values = ["RHEL-9.*_HVM-*-x86_64-*"]
  }

  filter {
    name   = "state"
    values = ["available"]
  }
}

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  cluster_egress_cidrs = [for n in data.aws_nat_gateway.cluster : "${n.public_ip}/32" if n.public_ip != null && n.public_ip != ""]
  allowed_cidrs        = concat(local.cluster_egress_cidrs, var.extra_allowed_cidrs)
}

# Red aislada: el servicio vive fuera de la VPC del clúster.
resource "aws_vpc" "ext" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = { Name = var.name }
}

resource "aws_internet_gateway" "ext" {
  vpc_id = aws_vpc.ext.id
  tags   = { Name = var.name }
}

resource "aws_subnet" "ext" {
  vpc_id                  = aws_vpc.ext.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, 1)
  availability_zone       = data.aws_availability_zones.available.names[0]
  map_public_ip_on_launch = true

  tags = { Name = var.name }
}

resource "aws_route_table" "ext" {
  vpc_id = aws_vpc.ext.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.ext.id
  }

  tags = { Name = var.name }
}

resource "aws_route_table_association" "ext" {
  subnet_id      = aws_subnet.ext.id
  route_table_id = aws_route_table.ext.id
}

resource "aws_security_group" "ext" {
  name        = var.name
  description = "API externa para Connectivity Link: solo desde el cluster y CIDRs permitidos"
  vpc_id      = aws_vpc.ext.id

  tags = { Name = var.name }

  lifecycle {
    precondition {
      condition     = length(local.cluster_egress_cidrs) > 0 || length(var.extra_allowed_cidrs) > 0
      error_message = "La VPC del clúster no tiene NAT Gateways disponibles con IP pública. Define extra_allowed_cidrs explícitos para sus IPs de salida o corrige cluster_vpc_name."
    }
  }
}

resource "aws_vpc_security_group_ingress_rule" "api" {
  for_each = toset(local.allowed_cidrs)

  security_group_id = aws_security_group.ext.id
  cidr_ipv4         = each.value
  from_port         = var.api_port
  to_port           = var.api_port
  ip_protocol       = "tcp"
  description       = "API externa"
}

resource "aws_vpc_security_group_egress_rule" "all" {
  security_group_id = aws_security_group.ext.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

resource "aws_instance" "api" {
  ami                    = data.aws_ami.rhel9.id
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.ext.id
  vpc_security_group_ids = [aws_security_group.ext.id]

  user_data = templatefile("${path.module}/user-data.sh.tftpl", {
    api_port = var.api_port
  })
  user_data_replace_on_change = true

  metadata_options {
    http_tokens = "required"
  }

  tags = { Name = var.name }
}
