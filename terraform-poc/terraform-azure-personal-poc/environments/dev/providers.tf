# Ansible mapping: a provider block is like the connection plugin plus
# credentials for a collection. Every credential below is supplied by HCP
# Terraform as an environment variable on the workspace:
#
#   ARM_CLIENT_ID, ARM_CLIENT_SECRET, ARM_TENANT_ID, ARM_SUBSCRIPTION_ID
#
# Deliberately no hard-coded subscription or secret -- that keeps the repo
# safe to push and keeps auth entirely on the HCP side.

provider "azurerm" {
  features {}
}
