# AWX Site Survey Automation

The compliance job template's survey offers a **Site** dropdown so an engineer
can see which sites are available for automation without typing anything. The
dropdown's choices live in AWX's database, not in this repository, so adding a
site in NetBox does not update it on its own.

`playbooks/sync_survey_choices.yml` closes that gap. It reads the groups and
hosts of the NetBox-backed AWX inventory and rewrites the choices of the `site`
and `target_host` survey questions. Every other survey question is passed
through untouched.

## Division of labour

| Concern | Owner |
| --- | --- |
| Pulling NetBox devices and sites into AWX | The AWX inventory source (Update on Launch, or a sync schedule on the source) |
| Refreshing the survey dropdown from that inventory | This playbook, on an AWX schedule |
| Rejecting an invalid site at run time | `playbooks/site-device-target.yml`, which derives its allowlist from the live inventory |

The playbook deliberately does **not** trigger an inventory sync. Kicking a
NetBox sync on every run makes a cheap pair of reads into an expensive
operation, and AWX already schedules inventory updates natively.

## Setting it up in AWX

1. Create a job template pointing at `playbooks/sync_survey_choices.yml`. It
   runs entirely on `localhost`, so the inventory it is given does not matter.
2. Attach a **Red Hat Ansible Automation Platform** credential. AWX injects
   `CONTROLLER_HOST` and `CONTROLLER_OAUTH_TOKEN`, which the playbook reads.
   It asserts both are present and fails with a clear message if they are not.
   The token needs permission to read the inventory and edit the target job
   template's survey.
3. Add a schedule. Every 15–30 minutes is ample — the playbook makes three
   read requests and writes only when something actually changed.

## Variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `survey_inventory_id` | `4` | AWX inventory holding the NetBox-sourced `sites_*` groups |
| `survey_job_template_id` | `9` | Job template whose survey is refreshed |

Override either with extra vars if the IDs differ.

## Behaviour worth knowing

- **Idempotent.** The update is skipped when the computed specification matches
  what AWX already has, so a scheduled run reports `changed=0` most of the time.
- **Supports check mode.** `--check` reports the difference between the
  inventory and the survey and posts nothing.
- **Refuses to blank the dropdown.** If the inventory contains no `sites_*`
  groups the playbook fails and leaves the survey alone, rather than replacing
  the choices with an empty list.
- **Requires the questions to exist.** It refreshes the choices of a question
  whose variable is `site`; it does not create the question. A survey without
  one fails with a message saying so.
- **Drops a stale default.** If the currently selected default site is no longer
  in the inventory, the first available site becomes the default, so AWX cannot
  preselect a site that has left NetBox.
