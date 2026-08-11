from __future__ import annotations

import hashlib
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CLOUDFLARE_IPV4_CIDRS = [
    "173.245.48.0/20",
    "103.21.244.0/22",
    "103.22.200.0/22",
    "103.31.4.0/22",
    "141.101.64.0/18",
    "108.162.192.0/18",
    "190.93.240.0/20",
    "188.114.96.0/20",
    "197.234.240.0/22",
    "198.41.128.0/17",
    "162.158.0.0/15",
    "104.16.0.0/13",
    "104.24.0.0/14",
    "172.64.0.0/13",
    "131.0.72.0/22",
]


def load_yaml(path: Path) -> dict[str, Any]:
    import yaml

    with path.open("r", encoding="utf-8") as handle:
        value = yaml.safe_load(handle) or {}
    if not isinstance(value, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return value


def write_yaml(path: Path, value: dict[str, Any]) -> None:
    import yaml

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(value, handle, sort_keys=False, allow_unicode=False)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hcl_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(value, list):
        return "[" + ", ".join(_hcl_value(item) for item in value) + "]"
    if isinstance(value, dict):
        items = [f"  {key} = {_hcl_value(item)}" for key, item in value.items()]
        return "{\n" + "\n".join(items) + "\n}"
    raise TypeError(f"Unsupported HCL value: {value!r}")


def write_tfvars(path: Path, values: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Generated from configs/systems/*.yml.",
        "# Do not edit by hand.",
        "",
    ]
    lines.extend(f"{key} = {_hcl_value(value)}" for key, value in values.items())
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _secret_env_name(ref: str) -> str:
    if not ref.startswith("env:"):
        raise ValueError(f"Secret reference must use env:NAME, got {ref!r}")
    return ref.removeprefix("env:")


def _is_env_ref(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("env:")


def _resolve_env_ref(value: str, *, field: str, default: str | None = None) -> str:
    if not value.startswith("env:"):
        return value
    env_name = value.removeprefix("env:")
    env_value = os.environ.get(env_name, "")
    if env_value:
        return env_value
    if default is not None:
        return default
    raise ValueError(f"{field} references {env_name}, but the environment variable is not set")


def _split_list_env(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[,\n]+", value) if item.strip()]


def _resolve_string_list(
    value: Any,
    *,
    field: str,
    default: list[str] | None = None,
) -> list[str]:
    if _is_env_ref(value):
        env_name = str(value).removeprefix("env:")
        env_value = os.environ.get(env_name, "")
        if not env_value and default is not None:
            return list(default)
        resolved = _resolve_env_ref(str(value), field=field)
        return _split_list_env(resolved)
    if value is None:
        return list(default or [])
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        items: list[str] = []
        for index, item in enumerate(value):
            if _is_env_ref(item):
                resolved = _resolve_env_ref(str(item), field=f"{field}[{index}]")
                items.extend(_split_list_env(resolved))
            else:
                items.append(str(item))
        return items
    raise ValueError(f"{field} must be a string, env reference, or list of strings")


def _resolve_ssh_authorized_keys(ssh: dict[str, Any]) -> dict[str, str]:
    keys = ssh.get("authorized_keys", {})
    if not isinstance(keys, dict):
        raise ValueError("ssh.authorized_keys must be a mapping")
    return {
        name: _resolve_env_ref(str(value), field=f"ssh.authorized_keys.{name}")
        for name, value in keys.items()
    }


def _tool_config(tools: dict[str, Any], key: str, legacy_enabled_key: str) -> dict[str, Any]:
    value = tools.get(key)
    if isinstance(value, dict):
        return value
    return {"enabled": bool(tools.get(legacy_enabled_key, False))}


def render_config(*, system_path: Path, out_dir: Path) -> list[Path]:
    system = load_yaml(system_path)
    active_profile = system["compute_profiles"][system["active_profile"]]
    postgres = system["postgres"]
    access = system["access"]
    secrets = system.get("secrets", {})
    global_analytics = system.get("global_analytics", {})
    web_portal = system.get("web_portal", {})
    web_portal_tls = web_portal.get("tls", {})
    if web_portal_tls is None:
        web_portal_tls = {}
    if not isinstance(web_portal_tls, dict):
        raise ValueError("web_portal.tls must be a mapping when set")
    regions = system["regions"]
    global_analytics_enabled = bool(global_analytics.get("enabled", False))
    web_portal_enabled = bool(web_portal.get("enabled", False))
    global_analytics_anchor_region = str(
        global_analytics.get("anchor_region", next(iter(regions)))
    )
    web_portal_anchor_region = str(
        web_portal.get("anchor_region", global_analytics_anchor_region)
    )
    web_portal_private_cidr_expr = (
        "{{ (hostvars[groups.get('web_portals', [])[0]].private_ip ~ '/32') "
        "if (groups.get('web_portals', []) | length) > 0 else '127.0.0.1/32' }}"
    )
    ssh = system.get("ssh", {})
    ssh_authorized_keys = _resolve_ssh_authorized_keys(ssh)
    ssh_private_key_path = _resolve_env_ref(
        str(ssh.get("private_key_path", "~/.ssh/id_ed25519")),
        field="ssh.private_key_path",
        default="~/.ssh/id_ed25519",
    )
    admin_ipv4_cidrs = _resolve_string_list(
        access.get("admin_ipv4_cidrs"),
        field="access.admin_ipv4_cidrs",
    )
    web_ipv4_cidrs = _resolve_string_list(
        access.get("web_ipv4_cidrs"),
        field="access.web_ipv4_cidrs",
        default=["0.0.0.0/0"],
    )
    if web_portal_enabled and bool(web_portal_tls.get("cloudflare_proxy", False)):
        web_ipv4_cidrs = list(dict.fromkeys([*web_ipv4_cidrs, *CLOUDFLARE_IPV4_CIDRS]))
    database_client_ipv4_cidrs = _resolve_string_list(
        access.get("database_client_ipv4_cidrs"),
        field="access.database_client_ipv4_cidrs",
    )
    global_analytics_public_access_cidrs = _resolve_string_list(
        global_analytics.get("public_access_cidrs", []),
        field="global_analytics.public_access_cidrs",
    )
    written: list[Path] = []

    for region_name, region in regions.items():
        tfvars = {
            "project_tag": system["project_tag"],
            "region_code": region["vultr_region"],
            "existing_vpc_id": region.get("existing_vpc_id", ""),
            "existing_vpc_cidr": region.get("existing_vpc_cidr", ""),
            "ssh_keys": ssh_authorized_keys,
            "admin_ipv4_cidrs": admin_ipv4_cidrs,
            "web_ipv4_cidrs": web_ipv4_cidrs,
            "db_access_ipv4_cidrs": database_client_ipv4_cidrs,
            "backend_count": 0,
            "worker_count": region.get("worker_count", 2),
            "compute_resource_type": active_profile["resource_type"],
            "backend_plan": active_profile["coordinator_plan"],
            "coordinator_plan": active_profile["coordinator_plan"],
            "worker_plan": active_profile["worker_plan"],
            "web_portal_enabled": bool(
                web_portal_enabled and region_name == web_portal_anchor_region
            ),
            "web_portal_plan": web_portal.get(
                "plan", active_profile.get("web_portal_plan", "vhf-1c-2gb")
            ),
            "postgres_version": postgres["version"],
            "citus_package": postgres["citus_package"],
            "app_db_name": postgres["app_db"],
            "app_db_user": postgres["app_user"],
            "tags": region.get("tags", [region_name, "citus"]),
        }
        if region_name == global_analytics_anchor_region:
            tfvars.update(
                {
                    "global_analytics_client_enabled": global_analytics_enabled,
                    "global_analytics_client_region_code": global_analytics.get(
                        "vultr_region", region["vultr_region"]
                    ),
                    "global_analytics_client_plan": active_profile["analytics_plan"],
                    "global_analytics_client_resource_type": active_profile["resource_type"],
                    "global_analytics_client_attach_vpc": global_analytics.get(
                        "attach_vpc", False
                    ),
                }
            )
        path = out_dir / "terraform" / "envs" / region_name / "terraform.tfvars"
        write_tfvars(path, tfvars)
        written.append(path)

    all_yml = {
        "ansible_user": "root",
        "ansible_become": True,
        "ssh_access_user": "root",
        "ssh_authorized_keys": list(ssh_authorized_keys.values()),
        "ansible_ssh_private_key_file": ssh_private_key_path,
        "postgresql_version": postgres["version"],
        "citus_package": postgres["citus_package"],
        "postgresql_admin_password": "{{ lookup('env', '"
        + _secret_env_name(secrets["postgres_admin_password"])
        + "') }}",
        "postgresql_app_db": postgres["app_db"],
        "postgresql_app_user": postgres["app_user"],
        "postgresql_app_password": "{{ lookup('env', '"
        + _secret_env_name(secrets["app_db_password"])
        + "') }}",
        "postgresql_max_connections": postgres.get("max_connections", 300),
        "postgresql_shared_preload_libraries": ",".join(
            postgres.get("shared_preload_libraries", ["citus", "pg_stat_statements"])
        ),
        "postgresql_pg_stat_statements_track": postgres.get(
            "pg_stat_statements_track", "all"
        ),
        "citus_enable_repartition_joins": bool(
            postgres.get("citus_enable_repartition_joins", True)
        ),
        "postgresql_allowed_cidrs": database_client_ipv4_cidrs,
        "master_regimes_git_pat": "{{ lookup('env', 'MASTER_REGIMES_GIT_PAT') }}",
        "master_regimes_git_username": (
            "{{ lookup('env', 'MASTER_REGIMES_GIT_USERNAME') "
            "| default('x-access-token', true) }}"
        ),
        "analytics_node_enabled": global_analytics_enabled,
        "global_analytics_anchor_region": global_analytics_anchor_region,
        "analytics_node_postgresql_enabled": bool(
            global_analytics.get("postgresql_enabled", True)
        ),
        "analytics_node_postgresql_version": global_analytics.get(
            "postgresql_version", postgres["version"]
        ),
        "analytics_node_postgresql_app_db": global_analytics.get("app_db", "analytics"),
        "analytics_node_postgresql_app_user": global_analytics.get("app_user", "analytics"),
        "analytics_node_postgresql_admin_password": "{{ lookup('env', '"
        + _secret_env_name(secrets["postgres_admin_password"])
        + "') }}",
        "analytics_node_postgresql_experiment_user": "postgres",
        "analytics_node_postgresql_experiment_password": "{{ lookup('env', '"
        + _secret_env_name(secrets["postgres_admin_password"])
        + "') }}",
        "analytics_node_postgresql_listen_addresses": (
            "0.0.0.0,::1" if web_portal_enabled else "127.0.0.1,::1"
        ),
        "analytics_node_postgresql_allowed_cidrs": (
            [
                "127.0.0.1/32",
                "::1/128",
                web_portal_private_cidr_expr,
            ]
            if web_portal_enabled
            else ["127.0.0.1/32", "::1/128"]
        ),
        "analytics_node_pgbouncer_allowed_cidrs": global_analytics_public_access_cidrs,
        "web_portal_enabled": web_portal_enabled,
        "web_portal_anchor_region": web_portal_anchor_region,
        "web_portal_allowed_cidrs": web_ipv4_cidrs,
        "web_portal_server_name": web_portal.get("server_name", "_"),
        "web_portal_tls_enabled": bool(web_portal_tls.get("enabled", False)),
        "web_portal_tls_domain": web_portal_tls.get(
            "domain", web_portal.get("server_name", "")
        ),
        "web_portal_tls_provider": web_portal_tls.get("provider", "letsencrypt"),
        "web_portal_tls_cloudflare_proxy": bool(
            web_portal_tls.get("cloudflare_proxy", False)
        ),
        "web_portal_tls_origin_cert_local_path": web_portal_tls.get(
            "origin_cert_local_path", ""
        ),
        "web_portal_tls_origin_key_local_path": web_portal_tls.get(
            "origin_key_local_path", ""
        ),
        "web_portal_tls_force_https": bool(web_portal_tls.get("force_https", True)),
        "web_portal_db_readonly_user": web_portal.get("db_readonly_user", "prof_demo"),
        "web_portal_db_readonly_password": "{{ lookup('env', '"
        + _secret_env_name(web_portal["db_readonly_password"])
        + "') }}" if web_portal_enabled else "",
        "web_portal_basic_auth_users": "{{ lookup('env', '"
        + _secret_env_name(web_portal["basic_auth_users"])
        + "') }}" if web_portal_enabled else "",
        "web_portal_viewer_auth_users": "{{ lookup('env', '"
        + _secret_env_name(web_portal["viewer_auth_users"])
        + "') }}" if web_portal_enabled else "",
        "web_portal_viewer_auth_disabled": bool(
            web_portal.get("viewer_auth_disabled", False)
        ),
        "web_portal_app_source_mode": web_portal.get("app_source_mode", "local"),
        "web_portal_apps_repo": web_portal.get("apps_repo", ""),
        "web_portal_apps_branch": web_portal.get("apps_branch", "main"),
        "web_portal_master_regimes_branch": web_portal.get(
            "master_regimes_branch", "main"
        ),
        "web_portal_master_regimes_infra_branch": web_portal.get(
            "master_regimes_infra_branch", "main"
        ),
        "web_portal_apps_repo_dir": web_portal.get(
            "apps_repo_dir", "/opt/master-regimes-apps"
        ),
        "web_portal_apps_cloudb_subdir": web_portal.get(
            "apps_cloudb_subdir", "apps/cloudb-web"
        ),
        "web_portal_apps_viewer_subdir": web_portal.get(
            "apps_viewer_subdir", "apps/regime-diagnosis-viewer"
        ),
        "web_portal_cloudb_web_local_source_hint": web_portal.get(
            "cloudb_web_local_source_hint", "../cloudb-web"
        ),
        "web_portal_viewer_local_source_hint": web_portal.get(
            "viewer_local_source_hint",
            "../master-regimes-apps/apps/regime-diagnosis-viewer",
        ),
        "web_portal_viewer_snapshot_local_path": web_portal.get(
            "viewer_snapshot_local_path",
            "../master-regimes-apps/apps/regime-diagnosis-viewer/public/diagnosis-data.json",
        ),
    }
    if global_analytics_enabled:
        all_yml["analytics_node_postgresql_app_password"] = (
            "{{ lookup('env', '"
            + _secret_env_name(secrets["analytics_db_password"])
            + "') }}"
        )
        remote_regions: dict[str, dict[str, object]] = {}
        for region_name in regions:
            coordinator_selector = (
                "groups.get('coordinators', []) | select('match', '^"
                + region_name
                + "-')"
            )
            coordinator = coordinator_selector + " | first"
            coordinator_count = coordinator_selector + " | list | length"
            remote_regions[region_name] = {
                "host": (
                    "{{ hostvars["
                    + coordinator
                    + "].private_ip | default(hostvars["
                    + coordinator
                    + "].ansible_host) if ("
                    + coordinator_count
                    + ") > 0 else '' }}"
                ),
                "port": 5432,
                "db": "{{ postgresql_app_db }}",
                "user": "{{ postgresql_admin_user | default('postgres') }}",
                "password": "{{ postgresql_admin_password }}",
                "sslmode": "verify-ca",
            }
        all_yml["analytics_node_remote_regions"] = remote_regions
    else:
        all_yml["analytics_node_postgresql_app_password"] = ""

    tools = system.get("tools", {})
    citus_datagen = _tool_config(tools, "citus_datagen", "citus_datagen_enabled")
    psql_benchmarks = _tool_config(tools, "psql_benchmarks", "psql_benchmarks_enabled")
    analytics_client = _tool_config(tools, "analytics_client", "analytics_client_enabled")

    all_yml["citus_datagen_enabled"] = bool(citus_datagen.get("enabled", False))
    all_yml["citus_datagen_git_clone_suffix"] = citus_datagen.get("repo", "")
    all_yml["citus_datagen_git_branch"] = citus_datagen.get("branch", "main")
    all_yml["psql_benchmarks_enabled"] = bool(psql_benchmarks.get("enabled", False))
    all_yml["psql_benchmarks_git_clone_suffix"] = psql_benchmarks.get("repo", "")
    all_yml["psql_benchmarks_git_branch"] = psql_benchmarks.get("branch", "main")
    all_yml["analytics_node_git_clone_suffix"] = analytics_client.get("repo", "")
    all_yml["analytics_node_git_branch"] = analytics_client.get("branch", "main")

    ansible_path = out_dir / "ansible" / "group_vars" / "all.yml"
    write_yaml(ansible_path, all_yml)
    written.append(ansible_path)

    inventory = {
        "all": {
            "children": {
                "coordinators": {"hosts": {}},
                "workers": {"hosts": {}},
                "analytics_clients": {"hosts": {}},
            }
        }
    }
    inventory_path = out_dir / "inventory" / "hosts.yml"
    write_yaml(inventory_path, inventory)
    written.append(inventory_path)

    manifest = {
        "system_id": system["system_id"],
        "created_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source_config": str(system_path),
        "source_config_sha256": sha256_file(system_path),
        "active_profile": system["active_profile"],
        "regions": regions,
        "postgres": postgres,
        "generated_files": [str(path.relative_to(out_dir)) for path in written],
    }
    manifest_path = out_dir / "system-manifest.yml"
    write_yaml(manifest_path, manifest)
    written.append(manifest_path)
    return written


def validate_config(system_path: Path) -> tuple[int, list[str]]:
    system = load_yaml(system_path)
    messages: list[str] = []
    failures = 0

    def ok(message: str) -> None:
        messages.append(f"[OK] {message}")

    def warn(message: str) -> None:
        messages.append(f"[WARN] {message}")

    def fail(message: str) -> None:
        nonlocal failures
        failures += 1
        messages.append(f"[FAIL] {message}")

    if system.get("provider") != "vultr":
        warn("provider is not vultr; old Terraform modules may need changes")
    else:
        ok("provider: vultr")

    active = system.get("active_profile")
    if active in system.get("compute_profiles", {}):
        ok(f"active profile exists: {active}")
    else:
        fail(f"active profile missing from compute_profiles: {active}")

    postgres = system.get("postgres", {})
    version = str(postgres.get("version", ""))
    citus_package = str(postgres.get("citus_package", ""))
    if version and f"postgresql-{version}-citus" in citus_package:
        ok(f"PostgreSQL/Citus package match: {version} / {citus_package}")
    else:
        fail("postgres.version and postgres.citus_package do not match")

    regions = system.get("regions", {})
    if set(regions) >= {"eu", "us", "apac"}:
        ok("regions include eu, us and apac")
    elif set(regions) >= {"eu", "us"}:
        ok("regions include eu and us")
    elif "eu" in regions:
        ok("regions include eu single-region topology")
    else:
        warn("expected eu, eu/us or eu/us/apac regions for thesis topology")

    for name, secret_ref in system.get("secrets", {}).items():
        if isinstance(secret_ref, str) and secret_ref.startswith("env:"):
            ok(f"secret {name} uses env reference")
        else:
            fail(f"secret {name} must use env:NAME reference")

    global_analytics = system.get("global_analytics", {})
    if global_analytics.get("enabled", False) and "analytics_db_password" not in system.get(
        "secrets", {}
    ):
        fail("global_analytics.enabled requires secrets.analytics_db_password")
    if global_analytics.get("enabled", False):
        anchor_region = str(global_analytics.get("anchor_region", next(iter(regions), "")))
        if anchor_region in regions:
            ok(f"global analytics anchor region exists: {anchor_region}")
        else:
            fail(f"global_analytics.anchor_region is not in regions: {anchor_region}")

    ssh = system.get("ssh", {})
    keys = ssh.get("authorized_keys", {})
    if not isinstance(keys, dict):
        fail("ssh.authorized_keys must be a mapping")
    elif any("replace-with" in str(value) for value in keys.values()):
        warn("ssh.authorized_keys contains placeholder values")
    elif keys:
        literal_keys = {
            name: value for name, value in keys.items() if not _is_env_ref(value)
        }
        env_refs = {
            name: str(value).removeprefix("env:")
            for name, value in keys.items()
            if _is_env_ref(value)
        }
        if literal_keys:
            warn("ssh.authorized_keys contains literal public keys; prefer env: references")
        if env_refs:
            missing = [env_name for env_name in env_refs.values() if not os.environ.get(env_name)]
            if missing:
                warn(
                    "ssh.authorized_keys env refs are configured but missing locally: "
                    + ", ".join(missing)
                )
            else:
                ok("ssh keys configured through environment references")
        elif literal_keys:
            ok("ssh keys configured")
    else:
        fail("no ssh.authorized_keys configured")

    private_key_path = str(ssh.get("private_key_path", ""))
    if _is_env_ref(private_key_path):
        env_name = private_key_path.removeprefix("env:")
        if os.environ.get(env_name):
            ok("ssh.private_key_path configured through environment reference")
        else:
            warn(f"ssh.private_key_path references missing local env var: {env_name}")
    elif private_key_path:
        warn("ssh.private_key_path is literal; prefer env:MASTER_REGIMES_SSH_PRIVATE_KEY_FILE")

    def check_cidr_field(mapping: dict[str, Any], key: str, field: str) -> None:
        value = mapping.get(key)
        values = value if isinstance(value, list) else [value]
        if value is None:
            fail(f"{field} is missing")
            return
        env_refs = [str(item).removeprefix("env:") for item in values if _is_env_ref(item)]
        literal_values = [
            str(item) for item in values if item is not None and not _is_env_ref(item)
        ]
        if any("203.0.113." in item for item in literal_values):
            fail(f"{field} contains documentation CIDR placeholder")
        if literal_values:
            warn(f"{field} contains literal CIDR values; prefer env: references")
        if env_refs:
            missing = [env_name for env_name in env_refs if not os.environ.get(env_name)]
            if missing:
                warn(f"{field} env refs are configured but missing locally: " + ", ".join(missing))
            else:
                ok(f"{field} configured through environment references")

    access = system.get("access", {})
    check_cidr_field(access, "admin_ipv4_cidrs", "access.admin_ipv4_cidrs")
    check_cidr_field(access, "web_ipv4_cidrs", "access.web_ipv4_cidrs")
    check_cidr_field(
        access,
        "database_client_ipv4_cidrs",
        "access.database_client_ipv4_cidrs",
    )

    if global_analytics.get("enabled", False):
        check_cidr_field(
            global_analytics,
            "public_access_cidrs",
            "global_analytics.public_access_cidrs",
        )

    return (1 if failures else 0), messages
