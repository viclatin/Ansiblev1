# Ansible mapping: this is the playbook that includes roles -- it decides what
# the dev environment looks like and passes values in. The reusable logic lives
# in ../../modules, not here.

locals {
  name_prefix = "${var.project}-${var.environment}"

  common_tags = merge(
    {
      project     = var.project
      environment = var.environment
      managed_by  = "terraform"
      workspace   = terraform.workspace
    },
    var.tags,
  )
}

module "resource_group" {
  source = "../../modules/resource_group"

  name     = "rg-${local.name_prefix}"
  location = var.location
  tags     = local.common_tags
}

# The resource group was originally declared directly in the root module as
# azurerm_resource_group.main. Moving it into a module changes its address, and
# without this block Terraform would plan to destroy and recreate it. `moved`
# rewrites the address in state instead, so the plan stays empty.
#
# Safe to delete once this change has been applied in every environment.
moved {
  from = azurerm_resource_group.main
  to   = module.resource_group.azurerm_resource_group.this
}
