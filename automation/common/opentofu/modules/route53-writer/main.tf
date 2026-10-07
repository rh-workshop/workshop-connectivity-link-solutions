data "aws_partition" "current" {}

resource "aws_iam_user" "dns" {
  name          = var.identity
  path          = "/rh-workshop/"
  force_destroy = false
  tags = merge(var.tags, {
    Project   = "rh-workshop"
    ManagedBy = "opentofu"
    Purpose   = var.purpose
  })
}

locals {
  # Un único generador mantiene idénticas las condiciones de ambas políticas.
  policies = { for kind, patterns in {
    inline  = var.record_patterns
    managed = var.managed_record_patterns
    } : kind => jsonencode({
      Version = "2012-10-17"
      Statement = [
        {
          Sid      = "ChangeAuthorizedRecords"
          Effect   = "Allow"
          Action   = ["route53:ChangeResourceRecordSets"]
          Resource = "arn:${data.aws_partition.current.partition}:route53:::hostedzone/${var.zone_id}"
          Condition = {
            "ForAllValues:StringLike" = {
              "route53:ChangeResourceRecordSetsNormalizedRecordNames" = patterns
            }
            "ForAllValues:StringEquals" = {
              "route53:ChangeResourceRecordSetsRecordTypes" = var.record_types
              "route53:ChangeResourceRecordSetsActions"     = ["CREATE", "UPSERT", "DELETE"]
            }
            Null = {
              "route53:ChangeResourceRecordSetsNormalizedRecordNames" = "false"
              "route53:ChangeResourceRecordSetsRecordTypes"           = "false"
              "route53:ChangeResourceRecordSetsActions"               = "false"
            }
          }
        },
        {
          Sid      = "ReadExistingZone"
          Effect   = "Allow"
          Action   = ["route53:GetHostedZone", "route53:ListResourceRecordSets"]
          Resource = "arn:${data.aws_partition.current.partition}:route53:::hostedzone/${var.zone_id}"
        },
        {
          Sid      = "FindHostedZones"
          Effect   = "Allow"
          Action   = ["route53:ListHostedZones", "route53:ListHostedZonesByName"]
          Resource = "*"
        },
        {
          Sid      = "PollChanges"
          Effect   = "Allow"
          Action   = ["route53:GetChange"]
          Resource = "arn:${data.aws_partition.current.partition}:route53:::change/*"
        },
      ]
  }) }
}

resource "aws_iam_user_policy" "dns" {
  name   = var.policy_name
  user   = aws_iam_user.dns.name
  policy = local.policies.inline
  lifecycle {
    precondition {
      condition     = length(local.policies.inline) <= 2048
      error_message = "La política inline supera el límite IAM de 2048 caracteres; restringe su alcance heredado."
    }
  }
}

resource "aws_iam_policy" "dns" {
  count  = var.managed_policy ? 1 : 0
  name   = "${var.identity}-${var.policy_name}"
  path   = "/rh-workshop/"
  policy = local.policies.managed
  tags   = aws_iam_user.dns.tags
  lifecycle {
    precondition {
      condition     = length(local.policies.managed) <= 6144
      error_message = "La política administrada supera el límite IAM de 6144 caracteres; restringe los patrones."
    }
  }
}

resource "aws_iam_user_policy_attachment" "dns" {
  count      = var.managed_policy ? 1 : 0
  user       = aws_iam_user.dns.name
  policy_arn = aws_iam_policy.dns[0].arn
}

resource "aws_iam_access_key" "dns" {
  user       = aws_iam_user.dns.name
  depends_on = [aws_iam_user_policy.dns, aws_iam_user_policy_attachment.dns]
}
