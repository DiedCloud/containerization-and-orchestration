"""Merge shop-owned configuration while retaining the existing Lab 2 stack."""
import copy
import json
import re


def merge_scrapes(existing, jobs):
    begin, end = "# BEGIN shop-CRD", "# END shop-CRD"
    base = re.sub(re.escape(begin) + r".*?" + re.escape(end), "", existing, flags=re.S).rstrip()
    if not jobs:
        return base + "\n"
    # JSON flow objects are valid YAML, avoiding an additional YAML dependency.
    return base + "\n" + begin + "\n" + "\n".join("- " + json.dumps(job) for job in jobs) + "\n" + end + "\n"


def merge_rules(existing, resources):
    retained = [group for group in existing if not group["name"].startswith("shop-cr/")]
    owned = []
    for resource in resources:
        for group in resource["spec"]["groups"]:
            group = copy.deepcopy(group)
            group["name"] = f"shop-cr/{resource['metadata']['namespace']}/{resource['metadata']['name']}/{group['name']}"
            owned.append(group)
    return retained + owned, owned


def dashboard_overrides(existing, enabled):
    providers = existing["dashboardProviders"]["dashboardproviders.yaml"]["providers"]
    providers = [provider for provider in providers if provider["name"] != "shop"]
    if enabled:
        providers.append({"name": "shop", "orgId": 1, "folder": "Labs", "type": "file", "disableDeletion": False,
                          "allowUiUpdates": False, "options": {"path": "/var/lib/grafana/dashboards/shop"}})
    maps = copy.deepcopy(existing.get("dashboardsConfigMaps", {}))
    if enabled or "shop" in maps:
        # null removes a previously managed key during Helm values merging.
        maps["shop"] = "shop-dashboard" if enabled else None
    return {"dashboardProviders": {"dashboardproviders.yaml": {"apiVersion": 1, "providers": providers}},
            "dashboardsConfigMaps": maps}
