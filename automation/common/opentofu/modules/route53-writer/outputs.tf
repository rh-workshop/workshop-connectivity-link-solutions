output "access_key_id" {
  value     = aws_iam_access_key.dns.id
  sensitive = true
}
output "secret_access_key" {
  value     = aws_iam_access_key.dns.secret
  sensitive = true
}
output "iam_user_name" { value = aws_iam_user.dns.name }
output "policy_json" { value = var.managed_policy ? aws_iam_policy.dns[0].policy : aws_iam_user_policy.dns.policy }
output "force_destroy" { value = aws_iam_user.dns.force_destroy }

output "inline_policy_json" { value = aws_iam_user_policy.dns.policy }
