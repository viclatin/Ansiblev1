from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "group_vars" / "remediation_catalog.yml"
CHANGES_DIR = ROOT / "changes"
TEST_INVENTORY_PATH = ROOT / "inventories" / "test" / "hosts.ini"
PRODUCTION_INVENTORY_PATH = ROOT / "inventories" / "production" / "hosts.ini"

REQUIRED_TOP_LEVEL_KEYS = {
    "change_id",
    "status",
    "target",
    "finding",
    "remediation",
    "implementation",
    "promotion",
}

FORBIDDEN_KEYS = {"command", "shell", "raw", "extra_vars", "playbook_override"}


def _load_yaml(path: Path):
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if data is not None else {}


def _load_catalog():
    catalog_doc = _load_yaml(CATALOG_PATH)
    assert "remediation_catalog" in catalog_doc, "group_vars/remediation_catalog.yml missing remediation_catalog"
    catalog = catalog_doc["remediation_catalog"]
    assert isinstance(catalog, dict) and catalog, "remediation_catalog must be a non-empty mapping"
    return catalog


def _inventory_groups(path: Path):
    assert path.exists(), f"{path.relative_to(ROOT)} not found"
    groups = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            group_header = stripped[1:-1]
            group_name = group_header.split(":", 1)[0]
            groups.add(group_name)
    return groups


def _iter_keys(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield str(key)
            yield from _iter_keys(value)
    elif isinstance(node, list):
        for value in node:
            yield from _iter_keys(value)


def test_change_manifest_files_exist():
    manifests = sorted(CHANGES_DIR.glob("*.yml"))
    assert manifests, "No change manifests found in changes/*.yml"


def test_change_manifests_match_catalog_contract():
    catalog = _load_catalog()
    test_inventory_groups = _inventory_groups(TEST_INVENTORY_PATH)
    production_inventory_groups = _inventory_groups(PRODUCTION_INVENTORY_PATH)
    manifests = sorted(CHANGES_DIR.glob("*.yml"))
    assert manifests, "No change manifests found in changes/*.yml"

    for manifest_path in manifests:
        manifest = _load_yaml(manifest_path)
        assert isinstance(manifest, dict), f"{manifest_path} must be a YAML mapping"

        missing = REQUIRED_TOP_LEVEL_KEYS - set(manifest.keys())
        assert not missing, f"{manifest_path} missing required keys: {sorted(missing)}"

        normalized_keys = {k.lower().replace("-", "_") for k in _iter_keys(manifest)}
        forbidden_present = sorted(FORBIDDEN_KEYS.intersection(normalized_keys))
        assert not forbidden_present, f"{manifest_path} contains forbidden keys: {forbidden_present}"

        remediation = manifest["remediation"]
        assert isinstance(remediation, dict), f"{manifest_path} remediation must be a mapping"
        remediation_id = remediation.get("remediation_id")
        assert remediation_id in catalog, (
            f"{manifest_path} uses remediation_id '{remediation_id}' not present in group_vars/remediation_catalog.yml"
        )

        expected = catalog[remediation_id]
        finding = manifest["finding"]
        assert isinstance(finding, dict), f"{manifest_path} finding must be a mapping"
        assert finding.get("control") == expected["control"], (
            f"{manifest_path} finding.control must match catalog control '{expected['control']}'"
        )

        evidence_report = finding.get("evidence_report")
        assert isinstance(evidence_report, str) and evidence_report, (
            f"{manifest_path} finding.evidence_report must be a non-empty string"
        )
        assert (ROOT / evidence_report).exists(), (
            f"{manifest_path} references missing evidence report: {evidence_report}"
        )

        implementation = manifest["implementation"]
        assert isinstance(implementation, dict), f"{manifest_path} implementation must be a mapping"
        expected_paths = {
            "playbook": expected["playbook"],
            "validation_playbook": expected["validation_playbook"],
            "rollback_playbook": expected["rollback_playbook"],
        }
        for key, expected_path in expected_paths.items():
            actual_path = implementation.get(key)
            assert actual_path == expected_path, (
                f"{manifest_path} {key} must match catalog path '{expected_path}', got '{actual_path}'"
            )
            resolved = ROOT / actual_path
            assert resolved.exists(), f"{manifest_path} references missing file: {actual_path}"

        target = manifest["target"]
        assert isinstance(target, dict), f"{manifest_path} target must be a mapping"

        test_group = target.get("test_inventory_group")
        assert test_group == "remediation_targets", (
            f"{manifest_path} test_inventory_group must be remediation_targets"
        )
        assert test_group in test_inventory_groups, (
            f"{manifest_path} test_inventory_group '{test_group}' not found in inventories/test/hosts.ini"
        )

        production_group = target.get("production_inventory_group")
        allowed_groups = expected.get("production_target_allowlist", [])
        assert production_group in allowed_groups, (
            f"{manifest_path} production_inventory_group '{production_group}' is not allow-listed for {remediation_id}"
        )
        assert production_group in production_inventory_groups, (
            f"{manifest_path} production_inventory_group '{production_group}' not found in inventories/production/hosts.ini"
        )

        promotion = manifest["promotion"]
        assert isinstance(promotion, dict), f"{manifest_path} promotion must be a mapping"
        assert promotion.get("test_required") == expected["test_required"], (
            f"{manifest_path} promotion.test_required must match catalog"
        )
        assert promotion.get("production_approval_required") == expected["production_approval_required"], (
            f"{manifest_path} promotion.production_approval_required must match catalog"
        )

        production_status = str(promotion.get("production_status", "")).upper()
        assert production_status == "NOT_AUTHORIZED", (
            f"{manifest_path} production_status must be NOT_AUTHORIZED until a human approval gate"
        )
