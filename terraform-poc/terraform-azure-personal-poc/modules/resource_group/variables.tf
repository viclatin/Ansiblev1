# Ansible mapping: these are a role's defaults/main.yml plus argument_specs --
# the contract a caller has to satisfy. Inputs without a default are required.

variable "name" {
  description = "Name of the resource group to create."
  type        = string

  validation {
    condition     = can(regex("^[a-zA-Z0-9._()-]{1,90}$", var.name)) && !endswith(var.name, ".")
    error_message = "name must be 1-90 characters of letters, digits, '.', '_', '(', ')' or '-', and must not end with a period."
  }
}

variable "location" {
  description = "Azure region the resource group lives in."
  type        = string
}

variable "tags" {
  description = "Tags applied to the resource group."
  type        = map(string)
  default     = {}
}
