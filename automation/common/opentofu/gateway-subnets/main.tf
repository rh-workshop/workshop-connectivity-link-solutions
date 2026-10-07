data "aws_vpc" "cluster" {
  id = var.vpc_id
}

data "aws_instances" "cluster" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.cluster.id]
  }
  filter {
    name   = "tag:kubernetes.io/cluster/${var.expected_cluster_id}"
    values = ["owned", "shared"]
  }
  instance_state_names = ["running"]

  lifecycle {
    postcondition {
      condition     = length(self.ids) > 0
      error_message = "No hay instancias running del clúster esperado en esta VPC. Comprueba InfrastructureName y vpc_id."
    }
  }
}

data "aws_internet_gateway" "existing" {
  filter {
    name   = "attachment.vpc-id"
    values = [data.aws_vpc.cluster.id]
  }
  filter {
    name   = "attachment.state"
    values = ["available"]
  }

  lifecycle {
    postcondition {
      condition     = can(regex("^igw-[a-z0-9]+$", self.id))
      error_message = "No hay un Internet Gateway existente y disponible asociado a esta VPC."
    }
  }
}

data "aws_subnet" "selected" {
  for_each = toset(var.subnet_ids)
  id       = each.value

  lifecycle {
    postcondition {
      condition     = self.vpc_id == var.vpc_id
      error_message = "La subred seleccionada no pertenece a la VPC autorizada."
    }
    postcondition {
      condition     = self.available_ip_address_count >= var.minimum_available_ips
      error_message = "La subred no tiene suficiente capacidad IP disponible."
    }
  }
}

data "aws_route_table" "public" {
  for_each  = toset(var.subnet_ids)
  subnet_id = each.value

  lifecycle {
    postcondition {
      condition = self.vpc_id == var.vpc_id && anytrue([for route in self.routes :
        route.cidr_block == "0.0.0.0/0" && route.gateway_id == data.aws_internet_gateway.existing.id
      ])
      error_message = "La tabla asociada a la subred debe pertenecer a la VPC y tener ruta 0.0.0.0/0 al IGW existente. Una ruta NAT no es pública."
    }
    postcondition {
      condition     = length(toset([for subnet in data.aws_subnet.selected : subnet.availability_zone])) == length(var.subnet_ids)
      error_message = "Selecciona una sola subred por zona de disponibilidad."
    }
  }
}
