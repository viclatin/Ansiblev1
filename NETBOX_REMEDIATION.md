# Remediate from the NetBox device page

A **Remediate** button on a device in NetBox launches the matching remediation
playbook in AWX against that device.

## Why it is built this way

A NetBox custom link cannot call the AWX API. Its whole schema is `link_text`,
`link_url`, `button_class`, `new_window` — it renders an `<a href>` and performs
a browser GET, so it can neither POST to AWX's launch endpoint nor carry an API
token. The link is therefore only an entry point; a **custom script** does the
work.

The link works because NetBox prefills a script's form from query parameters
(`ScriptView.get` calls `as_form(initial=normalize_querydict(request.GET))`), so
`?device={{ object.pk }}` arrives with the device already selected.

The control is selected with **Ansible tags**, not a variable. Each remediation
play carries a play-level tag, and AWX passes `job_tags` at launch. A templated
`import_playbook: remediate_{{ control }}.yml` was rejected: imports resolve at
parse time, before any assert can run, so an unvalidated value would be
interpolated straight into a file path.

## Setup

### 1. AWX job template

Create **Network - Remediation**:

| Setting | Value |
| --- | --- |
| Playbook | `playbooks/remediate-target.yml` |
| Project | Network Automation GitHub Project 3 |
| Inventory | NetBox Demo Inventory |
| Credentials | Cisco Lab SSH, Netbox-API |
| Prompt on launch | **Variables**, **Job Tags**, **Job Type** |

All three prompts are required: variables carry the device and site, job tags
carry the control, and job type allows a check-mode dry run. A template without
them silently ignores what the script sends.

### 2. NetBox configuration

Add to NetBox's `configuration.py`:

```python
AWX_URL = "http://192.168.1.95:30765"
AWX_TOKEN = "<AWX OAuth token permitted to launch this template>"
AWX_REMEDIATION_JT = <job template id>
```

Use an AWX token belonging to a user who can launch only this template, not a
full admin token — NetBox will hold it at rest.

### 3. Custom script

Customization → Scripts → Add, uploading `netbox/scripts/remediation.py`. It
registers as `remediation.RemediateDevice`.

### 4. Custom link — the button

Customization → Custom Links → Add:

| Field | Value |
| --- | --- |
| Object types | DCIM > Device |
| Name | `remediate` |
| Link text | `Remediate` |
| Link URL | see below |
| Button class | Red |
| New window | yes |

The link URL also preselects the failing control, so the engineer usually only
has to confirm. A `ChoiceVar` default is a class attribute and cannot depend on
the chosen device, but NetBox prefills a script form from every query
parameter — so the preselection is done here, where the device is in scope:

```jinja
/extras/scripts/remediation.RemediateDevice/?device={{ object.pk }}{% if object.cf.compliance_notes and object.cf.compliance_notes.startswith('Failed controls:') %}&control={{ object.cf.compliance_notes.split(':')[1].split(',')[0].strip().lower() }}{% endif %}
```

With `compliance_notes` of `Failed controls: SYSLOG` that yields
`?device=1&control=syslog`. With several failing controls it preselects the
first; with none it omits the parameter and the dropdown falls back to its own
default.

The script also **narrows the dropdown to the failing controls**. A `ChoiceVar`
fixes its choices when the class is defined, so this happens in an `as_form`
override that reads the device out of `initial` and filters the rendered
field. A device failing NTP and HTTP therefore offers exactly those two, with
NTP preselected.

Only the GET that renders the form carries `initial`; the POST that submits it
does not. Validation therefore still runs against the full choice list, so a
narrowed form cannot reject its own submission, and an API-driven run may still
name any control. Devices with nothing failing keep the full list, so a control
can be deliberately re-applied.

To show the button only on non-compliant devices, make the link text
conditional — a custom link whose text renders empty is not displayed:

```jinja
{% if object.cf.compliance_status != 'compliant' %}Remediate{% endif %}
```

## Using it

1. Open a device whose compliance chip is amber or red.
2. Click **Remediate**. The script form opens with the device filled in.
3. Pick the control. **Dry run is on by default** — it launches the AWX job as
   `job_type: check`, so `cisco.ios.ios_config` reports the change without
   applying it.
4. Review the AWX job linked in the script output.
5. Re-run with dry run cleared to apply, then re-run compliance to refresh the
   chip.

## Safety

- **An untagged run is refused.** Without a control tag the wrapper would apply
  all six remediations at once, so it asserts a tag was given.
- **Validation always runs.** The wrapper's validation play is tagged `always`;
  without that, a tagged run would skip the site allowlist and host checks
  entirely.
- **Only SYSLOG can be verified and reverted.** It is the sole control with
  validation and rollback playbooks. The script warns when applying any of the
  other five for real.
- **Mismatched and pointless runs are flagged.** The script reads the device's
  own `compliance_notes` and warns if the chosen control is not among the
  failing ones, or if the device reports no failing controls at all (naming the
  `compliance_checked` date, since a stale reading is the usual cause). It
  warns rather than blocks: re-applying a control deliberately is legitimate.
- **No automatic remediation.** There is deliberately no Event Rule firing on a
  compliance change. That would reconfigure switches with no human approval and
  bypass the change-manifest governance in this repository — `test_required`,
  `production_approval_required`, `production_target_allowlist` and the GitHub
  Actions promotion flow.
