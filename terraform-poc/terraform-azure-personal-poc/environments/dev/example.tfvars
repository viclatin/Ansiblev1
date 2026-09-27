# Sample values for the root module's input variables.
#
# This file is documentation only -- it is never applied. The HCP workspace is
# VCS-driven and reads its variable values from the workspace itself, so set
# real values there rather than committing a .tfvars file. Every other *.tfvars
# path is gitignored to keep secrets out of the repository.

project     = "tfpoc"
environment = "dev"
location    = "eastus"

tags = {
  owner       = "viclatin"
  cost_center = "personal-lab"
}
