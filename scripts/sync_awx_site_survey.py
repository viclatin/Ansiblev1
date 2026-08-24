#!/usr/bin/env python3
"""Synchronize NetBox site groups into an AWX job-template survey."""

from __future__ import annotations

import json
import os
import ssl
import sys
import time
from copy import deepcopy
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_PREFIX = "/api/v2"
SITE_GROUP_PREFIX = "sites_"


class AwxApiError(RuntimeError):
    """Raised when AWX returns an unsuccessful API response."""


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} must be set")
    return value


def _ssl_context() -> ssl.SSLContext | None:
    verify_ssl = os.environ.get("AWX_VERIFY_SSL", "true").strip().lower()
    if verify_ssl in {"0", "false", "no"}:
        return ssl._create_unverified_context()
    return None


class AwxClient:
    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.ssl_context = _ssl_context()

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        query: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{API_PREFIX}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            url,
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, context=self.ssl_context, timeout=30) as response:
                response_body = response.read().decode("utf-8")
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise AwxApiError(f"{method} {path} failed with HTTP {error.code}: {detail}") from error
        except URLError as error:
            raise AwxApiError(f"{method} {path} failed: {error.reason}") from error

        if not response_body:
            return {}
        result = json.loads(response_body)
        if not isinstance(result, dict):
            raise AwxApiError(f"{method} {path} returned an unexpected response")
        return result


def _all_results(client: AwxClient, path: str, query: dict[str, str] | None = None) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    next_path: str | None = path
    next_query = query
    while next_path:
        page = client.request("GET", next_path, query=next_query)
        page_results = page.get("results", [])
        if not isinstance(page_results, list):
            raise AwxApiError(f"GET {next_path} returned an invalid results collection")
        results.extend(item for item in page_results if isinstance(item, dict))
        next_url = page.get("next")
        if not next_url:
            break
        marker = f"{API_PREFIX}/"
        try:
            next_path = next_url[next_url.index(marker) + len(API_PREFIX) :]
        except (AttributeError, ValueError) as error:
            raise AwxApiError(f"GET {path} returned an invalid pagination URL") from error
        next_query = None
    return results


def _site_names(groups: list[dict[str, Any]]) -> list[str]:
    return sorted(
        group["name"][len(SITE_GROUP_PREFIX) :]
        for group in groups
        if isinstance(group.get("name"), str)
        and group["name"].startswith(SITE_GROUP_PREFIX)
        and len(group["name"]) > len(SITE_GROUP_PREFIX)
    )


def _survey_with_site_choices(survey_spec: dict[str, Any], sites: list[str]) -> dict[str, Any]:
    updated = deepcopy(survey_spec)
    questions = updated.get("spec")
    if not isinstance(questions, list):
        raise ValueError("AWX survey specification has no question list")

    for question in questions:
        if isinstance(question, dict) and question.get("variable") == "site":
            question["type"] = "multiplechoice"
            question["choices"] = "\n".join(sites)
            question["required"] = True
            return updated
    raise ValueError("AWX survey has no question with variable 'site'")


def _wait_for_inventory_update(client: AwxClient, update_url: str, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        marker = f"{API_PREFIX}/"
        try:
            update_path = update_url[update_url.index(marker) + len(API_PREFIX) :]
        except ValueError as error:
            raise AwxApiError(f"Inventory update returned invalid URL: {update_url}") from error
        update = client.request("GET", update_path)
        status = update.get("status")
        if status == "successful":
            return
        if status in {"failed", "error", "canceled"}:
            raise AwxApiError(f"NetBox inventory update ended with status {status!r}")
        time.sleep(5)
    raise TimeoutError("Timed out waiting for the NetBox inventory update")


def main() -> int:
    try:
        awx_url = _required_env("AWX_URL")
        awx_token = _required_env("AWX_OAUTH_TOKEN")
        inventory_id = _required_env("AWX_INVENTORY_ID")
        inventory_source_id = _required_env("AWX_NETBOX_INVENTORY_SOURCE_ID")
        job_template_id = _required_env("AWX_COMPLIANCE_JOB_TEMPLATE_ID")
        timeout_seconds = int(os.environ.get("AWX_INVENTORY_SYNC_TIMEOUT", "600"))

        client = AwxClient(awx_url, awx_token)
        update = client.request("POST", f"/inventory_sources/{inventory_source_id}/update/")
        update_url = str(update.get("url", ""))
        if not update_url:
            raise AwxApiError("AWX did not return an inventory update URL")
        _wait_for_inventory_update(client, update_url, timeout_seconds)

        sites = _site_names(_all_results(client, f"/inventories/{inventory_id}/groups/"))
        if not sites:
            raise AwxApiError("The synced inventory contains no sites_* groups; survey was not changed")

        survey_path = f"/job_templates/{job_template_id}/survey_spec/"
        current_survey = client.request("GET", survey_path)
        updated_survey = _survey_with_site_choices(current_survey, sites)
        client.request("POST", survey_path, payload=updated_survey)
        print(f"Updated AWX site survey with {len(sites)} site(s): {', '.join(sites)}")
        return 0
    except (AwxApiError, TimeoutError, ValueError, json.JSONDecodeError) as error:
        print(f"AWX site survey sync failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())