# terraform-azure-personal-poc

Terraform Azure personal proof-of-concept project to learn infrastructure automation for:

- Azure cloud resources
- ServiceNow integration workflows
- HCP Terraform automation pipelines

## Goal

Build practical Terraform knowledge with Ansible-oriented explanations so a network engineer can quickly map familiar concepts to Terraform patterns.

## Terraform vs Ansible (quick mapping)

- **Inventory / hosts (Ansible)** → **Providers + resources (Terraform)**
- **Playbooks + roles (Ansible)** → **Modules + root module composition (Terraform)**
- **Idempotent task runs (Ansible)** → **Declarative desired state + `terraform plan`/`apply`**
- **Variables in group_vars/host_vars (Ansible)** → **Input variables (`variables.tf`, `*.tfvars`)**
- **Facts and registered outputs (Ansible)** → **Data sources + outputs**
- **Ansible Tower/AWX pipelines** → **HCP Terraform workspaces, runs, and policy checks**

## Repository layout

```
environments/dev/    the dev root module (HCP working directory)
modules/             reusable building blocks -- Terraform's answer to roles
docs/structure.md    why the tree is split this way, and how to add to it
```

Modules are to Terraform what roles are to Ansible, and each environment gets
its own directory plus its own HCP workspace so their state stays separate.
See [docs/structure.md](docs/structure.md) for the full explanation.

## Typical workflow (compared to Ansible)

1. Define infrastructure as code in Terraform (`.tf`) files (similar to writing a playbook/role).
2. Run `terraform init` (similar to preparing modules/collections and environment dependencies).
3. Run `terraform plan` to preview changes (similar to checking what Ansible tasks would change).
4. Run `terraform apply` to enforce desired state (similar to running an idempotent playbook).
5. Integrate change/approval flow with ServiceNow and execute through HCP Terraform pipelines.
