from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

from azure_res_validator.types import ActualResource


RESOURCE_TYPE_TO_ARM = {
    "azure vm machine": "microsoft.compute/virtualmachines",
    "azure sql database": "microsoft.sql/servers/databases",
    "azure appservice plan": "microsoft.web/serverfarms",
}


class AzureCliError(RuntimeError):
    pass


def _resolve_az_executable() -> str:
    candidates = [
        shutil.which("az"),
        shutil.which("az.cmd"),
        r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd",
    ]
    for candidate in candidates:
        if candidate:
            return candidate
    raise AzureCliError(
        "Azure CLI executable not found. Install Azure CLI and ensure 'az' is available."
    )


def ensure_device_login() -> None:
    az_executable = _resolve_az_executable()
    account_show = subprocess.run(
        [az_executable, "account", "show"],
        capture_output=True,
        text=True,
        check=False,
    )
    if account_show.returncode == 0:
        return

    login = subprocess.run(
        [az_executable, "login", "--use-device-code"],
        capture_output=False,
        text=True,
        check=False,
    )
    if login.returncode != 0:
        raise AzureCliError("Azure device authentication failed.")


def _run_az_graph_query(subscription_id: str, resource_group: str | None) -> list[dict[str, Any]]:
    az_executable = _resolve_az_executable()
    query = (
        "Resources "
        "| where subscriptionId =~ '{subscription}' "
        "| project id, name, type, resourceGroup, subscriptionId, "
        "vmSize=tostring(properties.hardwareProfile.vmSize), "
        "skuName=tostring(sku.name), "
        "currentServiceObjective=tostring(properties.currentServiceObjectiveName)"
    ).format(subscription=subscription_id)

    if resource_group:
        query += f" | where resourceGroup =~ '{resource_group}'"

    cmd = [
        az_executable,
        "graph",
        "query",
        "-q",
        query,
        "--subscriptions",
        subscription_id,
        "--first",
        "1000",
        "--output",
        "json",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise AzureCliError(
            f"Azure Resource Graph query failed: {result.stderr.strip() or result.stdout.strip()}"
        )

    payload = json.loads(result.stdout)
    return payload.get("data", [])


def _extract_configuration(arm_type: str, item: dict[str, Any]) -> str:
    normalized = (arm_type or "").lower()
    if normalized == "microsoft.compute/virtualmachines":
        return (item.get("vmSize") or "").strip()
    if normalized == "microsoft.web/serverfarms":
        return (item.get("skuName") or "").strip()
    if normalized == "microsoft.sql/servers/databases":
        return ((item.get("skuName") or item.get("currentServiceObjective") or "")).strip()
    return (item.get("skuName") or "").strip()


def fetch_resources(
    subscription_id: str,
    resource_group: str | None,
) -> dict[str, list[ActualResource]]:
    rows = _run_az_graph_query(subscription_id=subscription_id, resource_group=resource_group)

    by_name: dict[str, list[ActualResource]] = {}
    for row in rows:
        arm_type = (row.get("type") or "").lower()
        name = (row.get("name") or "").strip()
        if not name:
            continue
        config_value = _extract_configuration(arm_type=arm_type, item=row)
        actual = ActualResource(
            resource_id=(row.get("id") or "").strip(),
            name=name,
            arm_type=arm_type,
            configuration=config_value,
        )
        by_name.setdefault(name.lower(), []).append(actual)

    return by_name
