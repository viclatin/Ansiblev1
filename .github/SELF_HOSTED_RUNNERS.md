# Self-hosted runner policy

This repository uses dedicated self-hosted runners so network automation workflows can reach lab/production devices without exposing those networks to untrusted workloads.

## Required runner labels

1. ci-validation
- Purpose: static validation only.
- Network access: no access to test or production network devices.
- Typical workflows: lint, syntax checks, manifest-policy tests.

2. network-test
- Purpose: deploy and validate approved changes in test.
- Network access: test network only.
- Credentials: test-only credentials via GitHub environment secrets.

3. network-production
- Purpose: promote a previously tested commit SHA to production.
- Network access: production network only.
- Credentials: production credentials via GitHub environment secrets.
- Restrictions: strongest controls, human approval required.

## Event-safety rules

- Do not run untrusted pull-request code on any runner with production access.
- Keep pull_request jobs on ci-validation only.
- Run network-test and network-production workflows from workflow_dispatch (or protected push paths) with GitHub environment protection rules.

## Runner registration notes

- Register each runner with only the labels it needs.
- Do not add network-production label to a shared runner used for pull_request jobs.
- Keep runner hosts patched, isolated, and monitored.

## Secrets policy

- Do not commit credentials in inventories or playbooks.
- Store device credentials in GitHub environment secrets (test/prod) or approved secrets platform.
