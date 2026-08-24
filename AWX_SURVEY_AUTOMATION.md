# AWX Site Survey Automation

The `Sync AWX Site Survey` GitHub Actions workflow runs every five minutes.
It starts an AWX NetBox inventory-source sync, waits for it to finish, reads
the resulting `sites_*` groups, and updates the compliance template's `site`
multiple-choice survey question. A NetBox site is therefore available in the
AWX launch dropdown after the next successful workflow run.

Configure these repository values before enabling the workflow:

| GitHub setting | Value |
| --- | --- |
| Actions variable `AWX_URL` | AWX base URL, for example `https://awx.example.com` |
| Actions secret `AWX_OAUTH_TOKEN` | OAuth token for an AWX user allowed to update the inventory source and job-template survey |
| Actions variable `AWX_INVENTORY_ID` | NetBox-backed AWX inventory ID |
| Actions variable `AWX_NETBOX_INVENTORY_SOURCE_ID` | NetBox inventory-source ID within that inventory |
| Actions variable `AWX_COMPLIANCE_JOB_TEMPLATE_ID` | Compliance job-template ID with the `site` survey variable |
| Actions variable `AWX_VERIFY_SSL` | `true` for trusted TLS certificates; use `false` only for a development controller with a self-signed certificate |

The AWX job template must have a survey question whose variable is exactly
`site`. The workflow preserves every other survey question and only replaces
the choices for that question.

The token needs permission to launch the inventory-source update and edit the
specified job template. Run the workflow manually once after configuration to
verify those permissions and populate the initial dropdown.