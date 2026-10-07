output "aws_load_balancer_subnet_ids" {
  description = "Lista para el perfil Ansible que configura infraestructura/anotaciones del Gateway."
  value       = var.subnet_ids
  depends_on  = [data.aws_instances.cluster, data.aws_route_table.public, data.aws_subnet.selected]
}

output "aws_load_balancer_subnets" {
  description = "Valor de service.beta.kubernetes.io/aws-load-balancer-subnets, sin espacios."
  value       = join(",", var.subnet_ids)
  depends_on  = [data.aws_instances.cluster, data.aws_route_table.public, data.aws_subnet.selected]
}

output "cluster_infrastructure_id" {
  value = var.expected_cluster_id
}
