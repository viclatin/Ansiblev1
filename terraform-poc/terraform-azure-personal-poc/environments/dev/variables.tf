# Ansible mapping: this is group_vars/all with type checking. Values are set
# on the HCP workspace (Terraform variables) rather than in a committed
# .tfvars file.

variable "project" {
  description = "Short project identifier used to build resource names."
  type        = string
  default     = "tfpoc"

  validation {
    condition     = can(regex("^[a-z0-9]{2,12}$", var.project))
    error_message = "project must be 2-12 lowercase letters or digits."
  }
}

variable "environment" {
  description = "Deployment environment, used in resource names and tags."
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "test", "prod"], var.environment)
    error_message = "environment must be one of: dev, test, prod."
  }
}

variable "location" {
  description = "Azure region for all resources in this root module."
  type        = string
  default     = "eastus"
}

variable "tags" {
  description = "Extra tags merged into the common tag set on every resource."
  type        = map(string)
  default     = {}
}
