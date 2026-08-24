#!/usr/bin/env python3
"""Recreate the objects captured in netbox/snapshot/ against a NetBox instance.

Written for the 3.2.8 -> 4.6.8 rebuild: the snapshot is read-only input, objects
are created in dependency order, and every step is idempotent (an object that
already exists is looked up and reused rather than duplicated).

Auth: NETBOX_URL and NETBOX_AUTH (the full Authorization header value, e.g.
"Bearer nbt_<key>.<token>" for a v2 token or "Token <value>" for v1).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SNAPSHOT = Path(__file__).resolve().parent.parent / "snapshot"
URL = os.environ["NETBOX_URL"].rstrip("/")
AUTH = os.environ["NETBOX_AUTH"]


def call(method: str, path: str, payload=None, query=None):
    url = f"{URL}/api{path}"
    if query:
        url = f"{url}?{urlencode(query)}"
    body = json.dumps(payload).encode() if payload is not None else None
    req = Request(url, data=body, method=method,
                  headers={"Authorization": AUTH, "Accept": "application/json",
                           "Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=30) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw else {}
    except HTTPError as e:
        raise SystemExit(f"{method} {path} -> HTTP {e.code}: {e.read().decode()[:400]}")


def load(name: str) -> list[dict]:
    return json.loads((SNAPSHOT / f"{name}.json").read_text())["results"]


def ensure(path: str, lookup: dict, payload: dict, label: str) -> int:
    """Return the id of a matching object, creating it if absent."""
    found = call("GET", path, query=lookup)["results"]
    if found:
        print(f"  = exists  {label}")
        return found[0]["id"]
    obj = call("POST", path, payload=payload)
    print(f"  + created {label}")
    return obj["id"]


print("Regions")
regions = {}
for r in load("dcim_regions"):
    regions[r["slug"]] = ensure("/dcim/regions/", {"slug": r["slug"]},
                                {"name": r["name"], "slug": r["slug"]}, r["name"])

print("Sites")
sites = {}
for s in load("dcim_sites"):
    body = {"name": s["name"], "slug": s["slug"], "status": s["status"]["value"]}
    if s.get("region"):
        body["region"] = regions[s["region"]["slug"]]
    sites[s["slug"]] = ensure("/dcim/sites/", {"slug": s["slug"]}, body, s["name"])

print("Manufacturers")
mfrs = {}
for m in load("dcim_manufacturers"):
    mfrs[m["slug"]] = ensure("/dcim/manufacturers/", {"slug": m["slug"]},
                             {"name": m["name"], "slug": m["slug"]}, m["name"])

print("Device types")
types = {}
for t in load("dcim_device-types"):
    body = {"model": t["model"], "slug": t["slug"],
            "manufacturer": mfrs[t["manufacturer"]["slug"]],
            "u_height": t.get("u_height", 1)}
    types[t["slug"]] = ensure("/dcim/device-types/", {"slug": t["slug"]}, body, t["model"])

print("Device roles")
roles = {}
for r in load("dcim_device-roles"):
    body = {"name": r["name"], "slug": r["slug"], "color": r["color"],
            "vm_role": r.get("vm_role", False)}
    roles[r["slug"]] = ensure("/dcim/device-roles/", {"slug": r["slug"]}, body, r["name"])

print("Platforms")
platforms = {}
for p in load("dcim_platforms"):
    body = {"name": p["name"], "slug": p["slug"]}
    if p.get("manufacturer"):
        body["manufacturer"] = mfrs[p["manufacturer"]["slug"]]
    platforms[p["slug"]] = ensure("/dcim/platforms/", {"slug": p["slug"]}, body, p["name"])

print("Devices")
devices = {}
for d in load("dcim_devices"):
    role = d.get("device_role") or d.get("role")  # renamed device_role -> role in 4.x
    body = {"name": d["name"],
            "site": sites[d["site"]["slug"]],
            "role": roles[role["slug"]],
            "device_type": types[d["device_type"]["slug"]],
            "status": d["status"]["value"]}
    if d.get("platform"):
        body["platform"] = platforms[d["platform"]["slug"]]
    if d.get("serial"):
        body["serial"] = d["serial"]
    devices[d["name"]] = ensure("/dcim/devices/", {"name": d["name"]}, body, d["name"])

print("Interfaces")
ifaces = {}
for i in load("dcim_interfaces"):
    dev = devices[i["device"]["name"]]
    key = (i["device"]["name"], i["name"])
    ifaces[key] = ensure("/dcim/interfaces/",
                         {"device_id": dev, "name": i["name"]},
                         {"device": dev, "name": i["name"], "type": i["type"]["value"]},
                         f'{i["device"]["name"]}::{i["name"]}')

print("IP addresses")
for a in load("ipam_ip-addresses"):
    body = {"address": a["address"], "status": a["status"]["value"]}
    obj = a.get("assigned_object")
    if obj:
        body["assigned_object_type"] = "dcim.interface"
        body["assigned_object_id"] = ifaces[(obj["device"]["name"], obj["name"])]
    ip_id = ensure("/ipam/ip-addresses/", {"address": a["address"]}, body, a["address"])

    # Re-point the device's primary IPv4 where the snapshot had one
    for d in load("dcim_devices"):
        if (d.get("primary_ip4") or {}).get("address") == a["address"]:
            call("PATCH", f'/dcim/devices/{devices[d["name"]]}/', {"primary_ip4": ip_id})
            print(f'  * primary_ip4 of {d["name"]} -> {a["address"]}')

print("\nDone.")
