# resource_group

Creates a single Azure resource group. Deliberately thin -- it exists to show
the module pattern rather than to abstract anything complicated.

A module is the Terraform equivalent of an Ansible role: reusable, parameterised,
and unaware of which environment is calling it. It declares no provider and no
backend; both are inherited from the root module that calls it.

## Usage

```hcl
module "resource_group" {
  source = "../../modules/resource_group"

  name     = "rg-tfpoc-dev"
  location = "eastus"
  tags     = { environment = "dev" }
}
```

## Inputs

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `name` | `string` | yes | Name of the resource group. |
| `location` | `string` | yes | Azure region. |
| `tags` | `map(string)` | no | Tags applied to the resource group. |

## Outputs

| Name | Description |
|------|-------------|
| `name` | Name of the resource group. |
| `id` | Fully qualified Azure resource ID. |
| `location` | Region it was created in. |
