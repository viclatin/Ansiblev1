# GitHub Environment Setup

This repository uses GitHub environments to gate access to deployment jobs and secrets.

## Environments to create

1. test
2. production

## Configure `test`

Repository -> Settings -> Environments -> New environment -> `test`

Recommended settings:
- Required reviewers: optional for lab; add if you want a manual hold before test deploys.
- Prevent self-review: optional.
- Deployment branches: protected branches only.
- Environment secrets: test-only credentials and connection details.
- Deployment restrictions: allow only workflows/jobs that deploy to test.
- Admin bypass: disable if your governance requires no bypass.

Suggested test secrets (example names):
- ANSIBLE_NET_USERNAME
- ANSIBLE_NET_PASSWORD
- ANSIBLE_ENABLE_PASSWORD
- TEST_DEVICE_HOST
- TEST_DEVICE_PORT

## Configure `production`

Repository -> Settings -> Environments -> New environment -> `production`

Required settings:
- Required reviewers: enabled.
- Prevent self-review: enabled.
- Deployment branches: protected branches only.
- Environment secrets: production-only credentials and connection details.
- Deployment restrictions: allow only approved production workflow/job.
- Admin bypass: disabled, if your plan/governance permits it.

Suggested production secrets (example names):
- ANSIBLE_NET_USERNAME
- ANSIBLE_NET_PASSWORD
- ANSIBLE_ENABLE_PASSWORD
- PROD_DEVICE_HOST
- PROD_DEVICE_PORT

## Security guardrails

- Do not store credentials in inventory or playbooks.
- Keep test and production secrets separate.
- Do not run untrusted pull_request code on runners with production network access.
- Keep production deployments tied to explicit approvals and exact tested commit SHAs.

## Current workflow mapping

- `.github/workflows/deploy-test.yml` targets environment `test`.
- Production environment `production` will be used by the production promotion workflow in a later step.

## Verification checklist

After configuration, verify:
- `test` and `production` environments are visible in repository settings.
- `production` shows required reviewers and prevent self-review enabled.
- Environment secrets are populated in the correct environment only.
- A manual `deploy-test` run can access `test` environment secrets.
- Production workflow (when added) pauses for approval before secrets are exposed.
