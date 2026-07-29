# Branch Protection Setup Guide

After your CI workflow completes its first successful run, enable branch protection on `main` with the following settings.

## Via GitHub UI (Recommended after first green run)

1. Go to your repository settings: https://github.com/viclatin/Ansiblev1/settings/branches
2. Click **Add rule** (or edit existing main rule if present)
3. Branch name pattern: `main`
4. Enable the following:

### Access restrictions
- [x] **Require a pull request before merging**
  - Dismiss stale pull request approvals when new commits are pushed
  - Require code review from: at least 1 approver
  - Require approval of the most recent reviewable push
- [x] **Require status checks to pass before merging**
  - Require branches to be up to date before merging
  - Required status checks:
    - `ansible-quality` (Ansible quality gates)
    - `python-quality` (Python quality gates)
- [x] **Require conversation resolution before merging**
- [x] **Restrict who can push to matching branches**
  - (Optional: restrict to admins or specific team members)

### Additional protections
- [x] **Dismiss stale pull request approvals when new commits are pushed**
- [x] **Include administrators**
- [x] **Restrict force pushes**
  - Allow force pushes by: (leave as "Nobody")
- [x] **Restrict deletions**

## Via GitHub CLI (if installed)

Once your first CI run is green, you can automate this with GitHub CLI:

```bash
gh api repos/viclatin/Ansiblev1/branches/main/protection \
  --input /dev/stdin <<'EOF'
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["ansible-quality", "python-quality"]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "dismissal_restrictions": {},
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": false,
    "required_approving_review_count": 1
  },
  "restrictions": null,
  "required_conversation_resolution": true,
  "allow_force_pushes": false,
  "allow_deletions": false
}
EOF
```

## Workflow Status Checks Reference

Your CI workflow defines two required status checks:

| Check Name | Job | Purpose |
|---|---|---|
| `ansible-quality` | Ansible quality gates | YAML lint, ansible-lint, syntax checks, collection validation |
| `python-quality` | Python quality gates | Python syntax checks, Ruff lint |

Both checks must pass before PRs can merge to `main`.

## Enforcement Timeline

1. **First CI run** (already triggered on push): Validates your current codebase
2. **Once passing**: Enable branch protection via GitHub UI or CLI
3. **All future PRs**: Must pass both checks + receive approval before merge

## Notes

- Branch protection cannot be applied via `.github/` workflows; it requires GitHub API or UI access
- Admin users can still force-push/delete if not explicitly restricted
- Status checks remain tied to workflow job names; if you rename jobs later, update protection rules to match
