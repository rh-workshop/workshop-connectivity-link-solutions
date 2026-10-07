resource "terraform_data" "https_client_ip" {
  # Este estado registra una excepción de configuración; el CCM sigue siendo dueño del TG.
  triggers_replace = [var.reviewed_configuration, var.preserve_client_ip, var.snapshot_path, var.expected_current_preserve_client_ip, var.approved_review_path, var.approved_review_sha256, filesha256("${path.module}/configure.py")]

  provisioner "local-exec" {
    command = "python3 \"$WK_HAIRPIN_HELPER\" --mode apply"
    environment = {
      WK_HAIRPIN_HELPER = abspath("${path.module}/configure.py")
      WK_HAIRPIN_CONFIG = jsonencode(merge(var.reviewed_configuration, {
        preserve_client_ip                  = var.preserve_client_ip
        snapshot_path                       = var.snapshot_path
        expected_current_preserve_client_ip = var.expected_current_preserve_client_ip
        approved_review_path                = var.approved_review_path
        approved_review_sha256              = var.approved_review_sha256
      }))
    }
  }
  # Sin provisioner destroy: nunca borrar, registrar targets ni modificar listeners.
}
