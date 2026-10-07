variable "identity" { type = string }
variable "purpose" { type = string }
variable "policy_name" { type = string }
variable "zone_id" { type = string }
variable "record_patterns" { type = list(string) }
variable "record_types" {
  type = list(string)
  validation {
    condition     = length(var.record_types) > 0 && alltrue([for value in var.record_types : contains(["A", "AAAA", "CNAME", "TXT"], value)])
    error_message = "Solo se admiten tipos A, AAAA, CNAME y TXT."
  }
}
variable "tags" { type = map(string) }

variable "managed_policy" {
  type    = bool
  default = false
}
variable "managed_record_patterns" {
  type    = list(string)
  default = []
}
