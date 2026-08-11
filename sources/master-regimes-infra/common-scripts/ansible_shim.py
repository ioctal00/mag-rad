#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import sys


def patch_ansible_local_rpc() -> None:
    """Disable Ansible 2.21's local RPC socket for static-inventory playbooks.

    The execution sandbox used by this workspace blocks socket bind/connect
    operations. Ansible 2.21 starts a local RPC manager for worker-to-controller
    inventory updates even before SSH happens, which fails with:

        Local RPC server did not start.

    The infrastructure playbooks use rendered static inventory and do not call
    add_host/add_group, so the RPC manager is unnecessary here.
    """

    if os.environ.get("MASTER_REGIMES_ANSIBLE_DISABLE_LOCAL_RPC", "1") in {
        "0",
        "false",
        "False",
        "no",
    }:
        return

    import ansible._internal._rpc_host as rpc_host

    class DisabledLocalManager:
        address = None
        authkey = b""

    rpc_host.LocalManager.shared_instance = classmethod(lambda cls: DisabledLocalManager())

    def disabled_rpc_client(cls):
        raise RuntimeError(
            "Ansible local RPC is disabled by master-regimes-infra. "
            "This is OK for static-inventory playbooks, but dynamic add_host/add_group "
            "requires running with MASTER_REGIMES_ANSIBLE_DISABLE_LOCAL_RPC=0."
        )

    rpc_host.AutoRegisterRPC.get_client = classmethod(disabled_rpc_client)


def run_cli(command: str, args: list[str]) -> int:
    sys.argv = [command, *args]
    if command == "ansible":
        from ansible.cli.adhoc import main
    elif command == "ansible-playbook":
        from ansible.cli.playbook import main
    elif command == "ansible-galaxy":
        from ansible.cli.galaxy import main
    elif command == "ansible-inventory":
        from ansible.cli.inventory import main
    elif command == "ansible-config":
        from ansible.cli.config import main
    else:
        raise SystemExit(f"Unsupported Ansible command for shim: {command}")
    return int(main() or 0)


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: ansible_shim.py <ansible-command> [args...]")

    command = Path(sys.argv[1]).name
    args = sys.argv[2:]
    patch_ansible_local_rpc()
    return run_cli(command, args)


if __name__ == "__main__":
    raise SystemExit(main())
