# Ansible mapping: a role's registered facts, handed back to the caller.

output "name" {
  description = "Name of the resource group."
  value       = azurerm_resource_group.this.name
}

output "id" {
  description = "Fully qualified Azure resource ID of the resource group."
  value       = azurerm_resource_group.this.id
}

output "location" {
  description = "Azure region the resource group was created in."
  value       = azurerm_resource_group.this.location
}
