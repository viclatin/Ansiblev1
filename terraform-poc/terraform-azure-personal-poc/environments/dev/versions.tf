# Ansible mapping: this file is the closest thing to ansible.cfg + collection
# requirements -- it pins the engine version, declares which "collections"
# (providers) we need, and says where state/execution lives.

terraform {
  required_version = "~> 1.16"

  # Execution happens in HCP Terraform, not on the local machine. Azure
  # credentials live on the workspace, so nothing here logs in to Azure.
  cloud {
    organization = "terraform-azure-personal-poc"

    workspaces {
      name = "terraform-azure-personal-poc"
    }
  }

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 5.0"
    }
  }
}
