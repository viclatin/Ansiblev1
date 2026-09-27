# Ansible mapping: registered facts, re-exported from the module so the
# workspace surfaces them in HCP.

output "resource_group_name" {
  description = "Name of the resource group created by this environment."
  value       = module.resource_group.name
}

output "resource_group_id" {
  description = "Fully qualified Azure resource ID of the resource group."
  value       = module.resource_group.id
}

output "location" {
  description = "Azure region the resource group was created in."
  value       = module.resource_group.location
}
