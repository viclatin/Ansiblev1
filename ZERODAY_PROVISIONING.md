# Zero-Day Access Switch Provisioning

Takes a brand-new, pre-staged Cisco access switch from its temporary bootstrap
address to the organisational baseline, using an AWX survey for the values that
change per deployment and NetBox for the device record and its uplinks.

This is **deliberately separate** from the compliance and remediation
workflows. It has its own job template, its own survey, its own variables (all
prefixed `zeroday_`), its own vars file and its own output folders. Nothing in
`compliance.yml`, `remediate-target.yml` or `remediation_catalog.yml` reads any
of it, and it reads none of theirs.

| Piece | Path |
| --- | --- |
| Entry playbook | `playbooks/provision-zeroday.yml` |
| Device play | `playbooks/provisioning/zeroday_baseline.yml` |
| Standards and bootstrap credential | `group_vars/zeroday_baseline.yml` |
| Survey hostname sync | `playbooks/sync_zeroday_survey.yml` |
| Pre-provisioning backups | `backups/zeroday/` |
| Provisioning reports | `reports/zeroday/` |

## Before it runs

Staging — how the switch gets its temporary address and SSH — is out of scope
here. The playbook assumes the switch is already reachable on its temporary IP
with the bootstrap credential.

In NetBox, the engineer must have:

1. Created the device with the correct device type, the hostname, and the
   serial number, and set its **status to Staged** so it appears in
   the survey dropdown.
2. Tagged every uplink interface with the tag **TRUNK**. The API filters on the
   tag's *slug*, which is `trunk` — that is what `zeroday_trunk_tag` holds.

A device that is missing from NetBox, or has no TRUNK-tagged interface, fails
the run before any configuration is pushed.

## What it configures

In this order:

1. **Organisational baseline** — not survey fields. Deliberately identical to
   what `group_vars/standards.yml` scores, so a freshly provisioned switch
   passes compliance at 100:
   `hostname`, `ntp server 8.8.8.8`, `snmp-server community victor RO`,
   `logging trap warnings`, `logging host 2.2.2.2`, `aaa new-model`,
   `no ip http server`, and `transport input ssh` on `line vty 0 4`.
2. **Management VLAN** — `vlan <n>` sent with no pre-check, before any VTP
   command, in every VTP mode (see below). A device that rejects it, such as a
   router, fails the run at this step.
3. **VTP** — domain, mode and password from the survey.
4. **Management SVI** — `interface Vlan<n>` with the final address and
   `no shutdown`, then `ip default-gateway`.
5. **Uplinks** — every TRUNK-tagged interface gets
   `description Uplink-trunk-link`, `switchport mode trunk` and `no shutdown`.
   `switchport trunk encapsulation dot1q` is attempted first and tolerated
   where the platform rejects it.
6. **Save** — once, at the end, and only if the running config changed.

It then re-reads `show running-config` and `show vtp status`, checks every item
above, writes `reports/zeroday/<hostname>_zeroday.json`, and fails the job if
any check did not pass.

**Not configured yet, by decision:** 802.1x, TACACS, password policy, banner.

### The temporary address is left in place

The final management address goes on the management SVI, but the temporary
address the job connected on is not removed. That keeps the session alive so
the play can verify its own work. Removing the temporary address is a separate,
deliberate step.

If the temporary address already sits on the management SVI itself, setting the
final address there would replace it and cut the session. The play checks
`show ip interface brief` for exactly that and refuses before changing anything.

### VTP client mode and the management VLAN

IOS rejects `vlan <n>` once a switch is in VTP client mode. A fresh switch is
in server mode, so the play creates the management VLAN **before** applying any
VTP setting, in every mode. Setting the VTP domain afterwards resets the
switch's configuration revision to 0, so joining the domain cannot overwrite the
existing VLAN database.

In **client** mode the switch then adopts the VTP server's VLAN list. The VLAN
created up front survives only if the server also has it; otherwise the next
VTP advertisement removes it. The job output warns about this. The VLAN itself is
not re-checked after provisioning, so confirm it on the switch. In **server** and **transparent** mode the VLAN stays as created.

## AWX setup

### 1. Job template — "Network - Zero-Day Provisioning"

| Setting | Value |
| --- | --- |
| Playbook | `playbooks/provision-zeroday.yml` |
| Project | Network Automation GitHub Project 3 |
| Inventory | Any — the switch is added at run time. NetBox Demo Inventory is fine. |
| Credentials | **Netbox-API only** |
| Survey | Enabled, as below |

**Do not attach a machine credential** such as Cisco Lab SSH. The bootstrap
credential is set per host at run time and overrides it anyway, so attaching one
only misleads whoever reads the template.

### 2. Survey

Variable names must match exactly.

| Question | Variable | Type | Notes |
| --- | --- | --- | --- |
| Hostname | `zeroday_hostname` | Multiple choice | Choices maintained by the sync job below |
| Temporary IP address | `zeroday_temp_ip` | Text | e.g. `192.168.1.50` |
| Management VLAN | `zeroday_mgmt_vlan` | Integer | 1–4094, not 1002–1005 |
| Final management IP | `zeroday_mgmt_ip` | Text | **CIDR form**, e.g. `10.10.20.5/24` |
| Default gateway | `zeroday_gateway` | Text | e.g. `10.10.20.1` |
| VTP mode | `zeroday_vtp_mode` | Multiple choice | `client`, `server`, `transparent` |
| VTP domain | `zeroday_vtp_domain` | Text | |
| VTP password | `zeroday_vtp_password` | **Password** | Masked in AWX |

Make every question required. The playbook re-validates all of them anyway and
names the offending field when one is wrong.

### 3. Survey sync — "Network - Zero-Day Survey Sync"

| Setting | Value |
| --- | --- |
| Playbook | `playbooks/sync_zeroday_survey.yml` |
| Credentials | Red Hat Ansible Automation Platform, Netbox-API |
| Extra vars | `zeroday_job_template_id: <id of the template above>` |
| Schedule | Every 15–30 minutes |

**Grant the sync's AWX user Admin on the provisioning template.** The
"AWX Self (survey sync)" credential authenticates as `awx-survey-sync`, which is
deliberately not a superuser. AWX only lets a user read or edit a survey with the
Admin role on that template, so without it the sync fails at "Read the current
survey specification" with HTTP 403. Grant it under the provisioning template's
Access tab — the same role that user already holds on the compliance,
remediation and rollback templates.

It lists NetBox devices whose status is in `zeroday_candidate_statuses`
(Staged only) and rewrites only the `zeroday_hostname` question's choices.
It never blanks the dropdown, refuses to run without an explicit template id,
and supports check mode. It is separate from `sync_survey_choices.yml` because
that one reads the AWX inventory, where a zero-day switch never appears — it has
no primary IP, so `nb_inventory` does not emit it.

## The bootstrap credential

`zeroday_bootstrap_user` / `zeroday_bootstrap_password` default to
`admin`/`admin` in `group_vars/zeroday_baseline.yml`, as requested. That is a
working credential for every freshly staged switch committed to git. Extra vars
of the same name take precedence, so it can be supplied at launch — for example
from an AWX custom credential type — without editing the file.

## Safety and guards

- Every survey answer is required and format-checked before NetBox is queried.
- The device must exist in NetBox exactly once, and carry at least one TRUNK
  uplink.
- The temporary address is never removed, and the run refuses if configuring
  the SVI would replace it.
- A full `show running-config` backup is written to `backups/zeroday/` before
  any change.
- The VTP password is kept out of the job log, the report, and verification.
- Check mode pushes nothing and says so; verification then describes the switch
  as it stands.

## Adding a playbook subdirectory

`playbooks/provisioning/` carries `group_vars` and `host_vars` symlinks back to
the repository root, like every other subdirectory under `playbooks/`. See
`group_vars/platforms_ios.yml` for why a subdirectory without them silently
loses its connection settings.
