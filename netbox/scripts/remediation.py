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
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dcim.models import Device
from django.contrib.contenttypes.models import ContentType
from extras.choices import JournalEntryKindChoices
from extras.models import JournalEntry
from extras.scripts import BooleanVar, ChoiceVar, ObjectVar, Script

# The AWX job usually finishes in well under a minute (remediation runs measured
# 12-19s, the compliance re-assessment 18-20s). The cap is generous so a slow
# device reports "still running" rather than a false failure.
AWX_POLL_SECONDS = 5
AWX_TIMEOUT_SECONDS = 300
AWX_TERMINAL = {"successful", "failed", "error", "canceled"}

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

# Rolling these back is destructive in its own right - removing AAA or changing
# the vty transport can lock out management, and re-enabling HTTP re-opens the
# finding - so their rollback playbooks demand rollback_confirm_disruptive.
CONTROLS_WITH_GUARDED_ROLLBACK = {"aaa", "ssh", "http"}


def _awx_get(url, token, path):
    request = Request(
        f"{url}{path}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def failing_controls(device):
    """Return the controls the last compliance run recorded as failing.

    compliance_notes is written by playbooks/compliance.yml as either
    "Failed controls: SYSLOG, HTTP" or "All 6 controls passing.".
    """
    notes = (device.cf.get("compliance_notes") or "").strip()
    marker = "Failed controls:"
    if not notes.startswith(marker):
        return []
    listed = notes[len(marker):]
    return [c.strip().lower() for c in listed.split(",") if c.strip()]


def _device_from_initial(initial):
    """Resolve the device a form is being rendered for, or None."""
    if not initial:
        return None
    value = initial.get("device")
    if isinstance(value, Device):
        return value
    try:
        return Device.objects.get(pk=int(value))
    except (TypeError, ValueError, Device.DoesNotExist):
        return None


class RemediateDevice(Script):
    class Meta:
        name = "Remediate Device"
        description = "Launch the AWX remediation job for one control on this device"
        field_order = ["device", "control", "dry_run"]
        # The script writes a JournalEntry recording each run, and NetBox rolls
        # database writes back unless the run is committed. NOTE: this checkbox
        # governs NetBox database writes only. Whether the SWITCH is touched is
        # controlled by dry_run below - the two are unrelated.
        commit_default = True

    device = ObjectVar(
        model=Device,
        description="Device to remediate (prefilled from the device page)",
    )
    control = ChoiceVar(
        choices=CONTROL_CHOICES,
        description="Which compliance control to remediate",
    )
    def as_form(self, data=None, files=None, initial=None):
        """Narrow the control list to the device's failing controls.

        A ChoiceVar's choices are fixed when the class is defined, so the
        filtering has to happen on the rendered form. The device arrives in
        `initial` from the ?device= query parameter the Remediate button sets.

        Only the GET that renders the form carries `initial`; the POST that
        submits it does not, so validation still runs against the full choice
        list and a narrowed form cannot reject its own submission.
        """
        form = super().as_form(data, files, initial)
        device = _device_from_initial(initial)
        if device is None:
            return form

        failing = failing_controls(device)
        if failing:
            form.fields["control"].choices = [
                choice for choice in CONTROL_CHOICES if choice[0] in failing
            ]
            form.fields["control"].help_text = (
                f"Showing only the controls failing on {device.name} as of "
                f"{device.cf.get('compliance_checked') or 'the last assessment'}."
            )
        else:
            form.fields["control"].help_text = (
                f"{device.name} has no failing controls recorded, so every "
                f"control is listed. Re-run the compliance assessment if that "
                f"looks out of date."
            )
        return form

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
                "control": control,
                # Always a single named device, never the whole site.
                "confirm_site_wide": "no",
            },
            # Sent both ways on purpose. The survey on the job template marks
            # these required, and AWX rejects a launch that omits a required
            # answer, so they must be present. job_tags stays as well so the
            # selection is unambiguous however the playbook resolves it.
            "job_tags": control,
            "job_type": "check" if dry_run else "run",
        }

        failing = failing_controls(device)
        status = device.cf.get("compliance_status")
        if not failing:
            self.log_warning(
                f"{device.name} reports compliance_status "
                f"'{status or 'unknown'}' with no failing controls recorded. "
                f"Remediating {control.upper()} may change nothing. Re-run the "
                f"compliance assessment if this reading looks stale "
                f"(last checked: {device.cf.get('compliance_checked') or 'never'})."
            )
        elif control not in failing:
            self.log_warning(
                f"{control.upper()} is not among the failing controls on "
                f"{device.name}. Currently failing: "
                f"{', '.join(c.upper() for c in failing)}. Continuing anyway, "
                f"but this run will most likely change nothing."
            )

        self.log_info(
            f"Launching {control.upper()} remediation against {device.name} "
            f"at site '{device.site.slug}' "
            f"({'check mode' if dry_run else 'APPLYING CHANGES'})."
        )
        if not dry_run and control in CONTROLS_WITH_GUARDED_ROLLBACK:
            self.log_warning(
                f"Reverting {control.upper()} is itself disruptive, so its "
                f"rollback requires rollback_confirm_disruptive=true on the "
                f"Network - Rollback job template. Be sure before applying."
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
        job_url = f"{awx_url}/#/jobs/playbook/{job_id}/output"
        self.log_info(f"AWX job {job_id} launched: {job_url}")

        # Wait for it, rather than returning immediately. A fire-and-forget
        # launch made success, failure and a dry run all look identical from
        # NetBox.
        status = self._wait_for_job(awx_url, awx_token, job_id)

        if status is None:
            self.log_warning(
                f"AWX job {job_id} was still running after "
                f"{AWX_TIMEOUT_SECONDS}s. It has not failed - follow it at "
                f"{job_url}."
            )
            self._journal(device, control, dry_run, job_id, job_url,
                          JournalEntryKindChoices.KIND_WARNING, "still running")
            return f"AWX job {job_id} still running; see {job_url}."

        if status != "successful":
            self.log_failure(f"AWX job {job_id} ended as '{status}'. See {job_url}.")
            self._journal(device, control, dry_run, job_id, job_url,
                          JournalEntryKindChoices.KIND_DANGER, status)
            return f"AWX job {job_id} {status}."

        if dry_run:
            self.log_success(
                f"Check-mode run finished. Nothing was changed on "
                f"{device.name} and NetBox was not updated. Review {job_url}, "
                f"then re-run with Dry run cleared to apply."
            )
            self._journal(device, control, dry_run, job_id, job_url,
                          JournalEntryKindChoices.KIND_INFO, "checked")
            return f"Dry run complete for {control.upper()} on {device.name}."

        # The job re-assesses compliance and republishes before it ends, so the
        # record is current by now - but `cf` is a cached_property, so
        # refresh_from_db() would not expose the new values. Re-fetch instead.
        device = Device.objects.get(pk=device.pk)
        new_status = device.cf.get("compliance_status") or "unknown"
        new_score = device.cf.get("compliance_score")
        summary = (
            f"{control.upper()} applied to {device.name}. "
            f"Now {new_status.upper()} ({new_score}/100)."
        )
        if new_status == "compliant":
            self.log_success(summary)
            kind = JournalEntryKindChoices.KIND_SUCCESS
        else:
            # The playbook can succeed while the device stays non-compliant,
            # because other controls may still be failing.
            still = failing_controls(device)
            self.log_warning(
                f"{summary} Still failing: "
                f"{', '.join(c.upper() for c in still) or 'unknown'}."
            )
            kind = JournalEntryKindChoices.KIND_WARNING
        self._journal(device, control, dry_run, job_id, job_url, kind,
                      f"{new_status} ({new_score}/100)")
        return summary

    def _wait_for_job(self, awx_url, awx_token, job_id):
        """Poll until the AWX job reaches a terminal state, or None on timeout."""
        deadline = time.monotonic() + AWX_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            try:
                job = _awx_get(awx_url, awx_token, f"/api/v2/jobs/{job_id}/")
            except (HTTPError, URLError) as error:
                self.log_warning(f"Could not read AWX job {job_id}: {error}")
                return None
            status = job.get("status")
            if status in AWX_TERMINAL:
                return status
            time.sleep(AWX_POLL_SECONDS)
        return None

    def _journal(self, device, control, dry_run, job_id, job_url, kind, outcome):
        """Record the run on the device, so the history outlives the job log."""
        JournalEntry.objects.create(
            assigned_object_type=ContentType.objects.get_for_model(Device),
            assigned_object_id=device.pk,
            created_by=self.request.user if getattr(self, "request", None) else None,
            kind=kind,
            comments=(
                f"**{control.upper()} remediation "
                f"{'(dry run)' if dry_run else '(applied)'}** - {outcome}.\n\n"
                f"AWX job [{job_id}]({job_url})."
            ),
        )
