from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

from master_regimes_infra.render import render_config, validate_config

REPO_ROOT = Path(__file__).resolve().parents[1]
SYSTEM = REPO_ROOT / "configs" / "systems" / "eu-us-apac-gac-vps.yml"
INVENTORY_SCRIPT = REPO_ROOT / "ansible" / "inventory" / "terraform_inventory.py"


def load_inventory_module():
    spec = importlib.util.spec_from_file_location("terraform_inventory", INVENTORY_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_n3_config_renders_all_regions(monkeypatch, tmp_path: Path) -> None:
    env = {
        "MASTER_REGIMES_SSH_PUBLIC_KEY": "ssh-ed25519 test-key",
        "MASTER_REGIMES_SSH_PRIVATE_KEY_FILE": "/tmp/test-key",
        "MASTER_REGIMES_ADMIN_IPV4_CIDRS": "203.0.113.10/32",
        "MASTER_REGIMES_WEB_IPV4_CIDRS": "203.0.113.10/32",
        "MASTER_REGIMES_DATABASE_CLIENT_IPV4_CIDRS": "203.0.113.10/32",
        "MASTER_REGIMES_GAC_PUBLIC_ACCESS_CIDRS": "203.0.113.10/32",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    failures, messages = validate_config(SYSTEM)
    assert failures == 0, messages
    out = tmp_path / "rendered"
    render_config(system_path=SYSTEM, out_dir=out)

    for region in ("eu", "us", "apac"):
        assert (out / "terraform" / "envs" / region / "terraform.tfvars").exists()

    all_vars = yaml.safe_load(
        (out / "ansible" / "group_vars" / "all.yml").read_text(encoding="utf-8")
    )
    remotes = all_vars["analytics_node_remote_regions"]
    assert list(remotes) == ["eu", "us", "apac"]
    assert all(remote["sslmode"] == "verify-ca" for remote in remotes.values())
    assert "^apac-" in remotes["apac"]["host"]


def test_inventory_discovers_apac_without_hardcoded_region_list(
    monkeypatch, tmp_path: Path
) -> None:
    module = load_inventory_module()
    tf_root = tmp_path / "terraform"
    for region in ("eu", "us", "apac"):
        env_dir = tf_root / "envs" / region
        env_dir.mkdir(parents=True)
        (env_dir / "main.tf").write_text("# test\n", encoding="utf-8")

    monkeypatch.setattr(module, "TF_BASE_DIR", tf_root)

    def fake_outputs(path: Path) -> dict:
        region = path.name
        return {
            "region": {"value": "ams"},
            "coordinator_public_ip": {"value": f"192.0.2.{len(region)}"},
            "coordinator_private_ip": {"value": f"10.0.{len(region)}.10"},
            "worker_public_ips": {"value": ["192.0.2.20", "192.0.2.21"]},
            "worker_private_ips": {"value": ["10.0.0.20", "10.0.0.21"]},
            "vpc_cidr": {"value": "10.0.0.0/16"},
        }

    monkeypatch.setattr(module, "tf_output_json", fake_outputs)
    inventory = module.build_inventory()
    children = inventory["all"]["children"]

    assert set(("eu", "us", "apac")) <= set(children)
    assert len(children["apac"]["hosts"]) == 3
    assert len(children["coordinators"]["hosts"]) == 3
    assert len(children["workers"]["hosts"]) == 6
    assert children["apac"]["hosts"]["apac-coord-1"]["logical_region"] == "apac"


def test_apac_extension_never_plans_or_applies_existing_region_stacks() -> None:
    script = (
        REPO_ROOT / "common-scripts" / "extend_eu_us_gac_with_apac.sh"
    ).read_text(encoding="utf-8")

    assert 'terraform -chdir="$APAC_TF_DIR" plan' in script
    assert 'terraform -chdir="$APAC_TF_DIR" apply' in script
    assert 'terraform -chdir="$EU_TF_DIR" plan' not in script
    assert 'terraform -chdir="$EU_TF_DIR" apply' not in script
    assert "US_TF_DIR" not in script
