"""NetBox custom script: launch an AWX remediation job for a device.

Reached from the Remediate button on the device page, which is a custom link
pointing at:

    /extras/scripts/remediation.RemediateDevice/?device={{ object.pk }}

NetBox prefills the form from query parameters (ScriptView.get calls
as_form(initial=normalize_querydict(request.GET))), so the device arrives
already selected and the engineer only confirms the control.

Configuration comes from the environment, not configuration.py: NetBox copies
only names listed in CONFIG_PARAMS onto django settings (settings.py:234), so a
custom AWX_URL there would never reach this script.

    AWX_URL              e.g. http://192.168.1.95:30765
    AWX_TOKEN            an AWX OAuth token permitted to launch the template
    AWX_REMEDIATION_JT   the numeric job template id

These are set on both the netbox and netbox-worker deployments. The worker
matters most: NetBox runs scripts as background jobs, so this code executes
there, not in the web pod.
"""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dcim.models import Device
from extras.scripts import BooleanVar, ChoiceVar, ObjectVar, Script

# Must match the play-level tags in playbooks/remediation/remediate_*.yml.
# The AWX job template refuses an untagged run, so one of these is always sent.
CONTROL_CHOICES = (
    ("syslog", "SYSLOG - centralised logging"),
    ("aaa", "AAA - centralised authentication"),
    ("ntp", "NTP - time synchronisation"),
    ("snmp", "SNMP - monitoring"),
    ("ssh", "SSH - management transport"),
    ("http", "HTTP - disable insecure management"),
)

# Only SYSLOG has validation and rollback playbooks; the rest apply without an
# automated way to verify or revert. Surfaced in the UI so the engineer knows.
CONTROLS_WITHOUT_ROLLBACK = {"aaa", "ntp", "snmp", "ssh", "http"}


class RemediateDevice(Script):
    class Meta:
        name = "Remediate Device"
        description = "Launch the AWX remediation job for one control on this device"
        field_order = ["device", "control", "dry_run"]
        commit_default = False

    device = ObjectVar(
        model=Device,
        description="Device to remediate (prefilled from the device page)",
    )
    control = ChoiceVar(
        choices=CONTROL_CHOICES,
        description="Which compliance control to remediate",
    )
    dry_run = BooleanVar(
        default=True,
        label="Dry run",
        description=(
            "Run in check mode: report the configuration change without "
            "applying it. Clear this only once the preview looks right."
        ),
    )

    def run(self, data, commit):
        device = data["device"]
        # The UI form resolves an ObjectVar to a model instance, but a run
        # submitted through the REST API arrives as a bare pk. Accept both so
        # the script behaves the same from the button and from automation.
        if not isinstance(device, Device):
            device = Device.objects.get(pk=device)

        control = data["control"]
        dry_run = data["dry_run"]

        awx_url = os.environ.get("AWX_URL", "").rstrip("/")
        awx_token = os.environ.get("AWX_TOKEN", "")
        template_id = os.environ.get("AWX_REMEDIATION_JT", "")
        if not (awx_url and awx_token and template_id):
            self.log_failure(
                "AWX_URL, AWX_TOKEN and AWX_REMEDIATION_JT must be set in the "
                "environment of the netbox-worker deployment before this "
                "script can launch a job."
            )
            return "Not configured."

        if not device.site:
            self.log_failure(
                f"{device} has no site, so the playbook cannot resolve a target."
            )
            return "Device has no site."

        payload = {
            "extra_vars": {
                "site": device.site.slug,
                "target_host": device.name,
            },
            # The control is selected by tag, never by interpolating a value
            # into a playbook path.
            "job_tags": control,
            "job_type": "check" if dry_run else "run",
        }

        self.log_info(
            f"Launching {control.upper()} remediation against {device.name} "
            f"at site '{device.site.slug}' "
            f"({'check mode' if dry_run else 'APPLYING CHANGES'})."
        )
        if not dry_run and control in CONTROLS_WITHOUT_ROLLBACK:
            self.log_warning(
                f"{control.upper()} has no rollback playbook. If this change is "
                f"wrong it must be reverted by hand."
            )

        request = Request(
            f"{awx_url}/api/v2/job_templates/{template_id}/launch/",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {awx_token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:500]
            self.log_failure(f"AWX rejected the launch (HTTP {error.code}): {detail}")
            return "Launch failed."
        except URLError as error:
            self.log_failure(f"Could not reach AWX at {awx_url}: {error.reason}")
            return "Launch failed."

        job_id = result.get("id") or result.get("job")
        self.log_success(
            f"AWX job {job_id} launched: "
            f"{awx_url}/#/jobs/playbook/{job_id}/output"
        )
        return f"Launched AWX job {job_id} for {control.upper()} on {device.name}."
