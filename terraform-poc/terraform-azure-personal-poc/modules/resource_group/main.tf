# Ansible mapping: this is the role's tasks/main.yml -- the reusable unit of
# work. It knows nothing about environments; the caller supplies every value.
#
# The resource is named "this" by convention: a module that manages a single
# resource of a type gives it that name, so the address reads
# module.resource_group.azurerm_resource_group.this.

resource "azurerm_resource_group" "this" {
  name     = var.name
  location = var.location
  tags     = var.tags
}




