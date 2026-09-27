# Repository structure

```
terraform-azure-personal-poc/
├── environments/          # one directory per environment (root modules)
│   └── dev/               # the dev root module -- HCP working directory
│       ├── main.tf        # what dev looks like: calls modules, passes values
│       ├── variables.tf   # inputs, with defaults
│       ├── outputs.tf     # values re-exported to the HCP workspace
│       ├── providers.tf   # provider configuration
│       ├── versions.tf    # cloud block, version pins
│       ├── example.tfvars # documentation only, never applied
│       └── .terraform.lock.hcl
├── modules/               # reusable building blocks, environment-agnostic
│   └── resource_group/
├── docs/
└── .github/workflows/
```

## Why it is split this way

**`environments/` holds root modules.** A root module is the thing Terraform is
actually pointed at: it configures the provider, declares where state lives, and
composes modules into a concrete environment. Each environment gets its own
directory *and its own HCP workspace*, which is what keeps dev state and prod
state separate. Nothing in `environments/dev` can affect prod, because they do
not share state.

**`modules/` holds reusable code.** A module declares no provider and no
backend; it inherits both from whichever root module calls it. That is precisely
what makes it reusable -- dev and prod can call the same module and get
consistently built resources with different inputs.

## Ansible mapping

| Terraform | Ansible |
|---|---|
| `modules/` | `roles/` |
| `environments/dev/main.tf` | a playbook that includes roles |
| `environments/dev/variables.tf` | `defaults/main.yml` |
| module input variables | role arguments / `argument_specs` |
| HCP workspace variables | `group_vars/<env>/` |
| separate workspace per environment | separate inventory per environment |

## Adding an environment

1. `cp -r environments/dev environments/test`
2. In `environments/test/versions.tf`, point the `cloud` block's `workspaces`
   block at a new workspace name.
3. Create that workspace in HCP with **working directory** `environments/test`
   and its own `ARM_*` credentials.
4. Adjust the variable defaults (`environment = "test"`).

The module is reused untouched -- only inputs change.

## Adding a module

1. Create `modules/<name>/` with `main.tf`, `variables.tf`, `outputs.tf` and a
   `README.md`.
2. Call it from an environment with a relative `source`, e.g.
   `source = "../../modules/<name>"`.
3. Run `terraform init` in that environment so Terraform picks up the new module.
