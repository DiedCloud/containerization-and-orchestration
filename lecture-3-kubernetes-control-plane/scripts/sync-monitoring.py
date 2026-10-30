"""Translate this lab's monitoring CRs into the existing Lab 2 Helm releases.

This is an explicit one-shot adapter, not Prometheus Operator. Supported:
ServiceMonitor matchLabels, matchNames, HTTP endpoints; PrometheusRule groups.
Generated overrides/evidence remain local. Run again after CR changes.
"""
import argparse
import copy
import json
from pathlib import Path
import re
import subprocess


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--context", default="kind-lab2")
parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "artifacts.local/05-monitoring")
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)


def run(command, data=None):
    result = subprocess.run(command, input=data, text=True, capture_output=True, timeout=360)
    if result.returncode:
        raise RuntimeError(f"{command}: {result.stdout}{result.stderr}")
    return result.stdout


def kube(*params, data=None):
    return run(["kubectl", "--context", args.context, *params], data)


def helm(*params):
    return run(["helm", "--kube-context", args.context, *params])


releases = json.loads(helm("list", "-n", "monitoring", "-o", "json"))
for release, chart in [("prometheus", "prometheus-29.38.1"), ("grafana", "grafana-10.5.15")]:
    assert next(r for r in releases if r["name"] == release)["chart"] == chart, "Unexpected chart version; inspect before updating"
prometheus = json.loads(helm("get", "values", "prometheus", "-n", "monitoring", "-o", "json"))
grafana = json.loads(helm("get", "values", "grafana", "-n", "monitoring", "-o", "json"))
# Private snapshots support local review without printing old values or credentials.
(args.output / "prometheus-before.json").write_text(json.dumps(prometheus, indent=2))
(args.output / "grafana-before.json").write_text(json.dumps(grafana, indent=2))
monitors = json.loads(kube("get", "servicemonitor", "-n", "shop", "-l", "app.kubernetes.io/instance=shop", "-o", "json"))["items"]
rules = json.loads(kube("get", "prometheusrule", "-n", "shop", "-l", "app.kubernetes.io/instance=shop", "-o", "json"))["items"]
assert len(monitors) == 2 and len(rules) == 1, "Install shop monitoring objects first"
jobs = []
for monitor in sorted(monitors, key=lambda m: m["metadata"]["name"]):
    spec = monitor["spec"]
    assert set(spec) <= {"selector", "namespaceSelector", "endpoints"}, "Unsupported ServiceMonitor fields"
    assert not spec["selector"].get("matchExpressions"), "Adapter supports matchLabels only"
    assert not spec.get("namespaceSelector", {}).get("any"), "Adapter requires explicit namespaces"
    for index, endpoint in enumerate(spec["endpoints"]):
        assert set(endpoint) <= {"port", "path", "interval", "scrapeTimeout", "scheme", "honorLabels"}, "Unsupported endpoint options"
        relabels = []
        for label, value in sorted(spec["selector"]["matchLabels"].items()):
            meta = "__meta_kubernetes_service_label_" + re.sub(r"[^A-Za-z0-9_]", "_", label)
            relabels.append({"source_labels": [meta], "action": "keep", "regex": re.escape(value)})
        relabels.extend([
            {"source_labels": ["__meta_kubernetes_endpoint_port_name"], "action": "keep", "regex": re.escape(endpoint["port"])},
            {"source_labels": ["__meta_kubernetes_endpoint_ready"], "action": "keep", "regex": "true"},
            {"source_labels": ["__meta_kubernetes_namespace"], "target_label": "namespace"},
            {"source_labels": ["__meta_kubernetes_service_name"], "target_label": "service"},
            {"source_labels": ["__meta_kubernetes_pod_name"], "target_label": "pod"},
        ])
        jobs.append({
            "job_name": f"serviceMonitor/{monitor['metadata']['namespace']}/{monitor['metadata']['name']}/{index}",
            "metrics_path": endpoint.get("path", "/metrics"),
            "scheme": endpoint.get("scheme", "http"),
            "scrape_interval": endpoint.get("interval", "15s"),
            "scrape_timeout": endpoint.get("scrapeTimeout", "5s"),
            "honor_labels": endpoint.get("honorLabels", False),
            "kubernetes_sd_configs": [{"role": "endpoints", "namespaces": {"names": spec.get("namespaceSelector", {}).get("matchNames", [monitor["metadata"]["namespace"]])}}],
            "relabel_configs": relabels,
        })

begin, end = "# BEGIN shop-CRD", "# END shop-CRD"
base = prometheus.get("extraScrapeConfigs", "")
base = re.sub(re.escape(begin) + r".*?" + re.escape(end), "", base, flags=re.S).rstrip()
# JSON flow objects are valid YAML, avoiding an additional local YAML dependency.
scrapes = base + "\n" + begin + "\n" + "\n".join("- " + json.dumps(job) for job in jobs) + "\n" + end + "\n"
old_groups = prometheus.get("serverFiles", {}).get("alerting_rules.yml", {}).get("groups", [])
groups = [g for g in old_groups if not g["name"].startswith("shop-cr/")]
new_groups = []
for resource in rules:
    for group in resource["spec"]["groups"]:
        group = copy.deepcopy(group)
        group["name"] = f"shop-cr/{resource['metadata']['namespace']}/{resource['metadata']['name']}/{group['name']}"
        new_groups.append(group)
groups.extend(new_groups)
assert sum(len(g["rules"]) for g in new_groups) == 3
check = kube("exec", "-i", "-n", "monitoring", "deployment/prometheus-server", "-c", "prometheus-server", "--",
             "/bin/promtool", "check", "rules", "/dev/stdin", data=json.dumps({"groups": new_groups}))
print(check, end="", flush=True)
prom_override = {"extraScrapeConfigs": scrapes, "serverFiles": {"alerting_rules.yml": {"groups": groups}}}
prom_path = args.output / "prometheus-overrides.json"
prom_path.write_text(json.dumps(prom_override, indent=2, ensure_ascii=False))
providers = grafana["dashboardProviders"]["dashboardproviders.yaml"]["providers"]
providers = [p for p in providers if p["name"] != "shop"]
providers.append({"name": "shop", "orgId": 1, "folder": "Labs", "type": "file", "disableDeletion": True,
                  "allowUiUpdates": False, "options": {"path": "/var/lib/grafana/dashboards/shop"}})
graf_override = {"dashboardProviders": {"dashboardproviders.yaml": {"apiVersion": 1, "providers": providers}},
                 "dashboardsConfigMaps": {"shop": "shop-dashboard"}}
graf_path = args.output / "grafana-overrides.json"
graf_path.write_text(json.dumps(graf_override, indent=2))
print(f"Read {len(monitors)} ServiceMonitor and {len(rules)} PrometheusRule: {len(jobs)} jobs, 3 alerts", flush=True)
print("Updating existing Prometheus; retaining Lab 2 jobs, rules and Alertmanager", flush=True)
print(helm("upgrade", "prometheus", "prometheus-community/prometheus", "--version", "29.38.1", "-n", "monitoring",
           "--reuse-values", "-f", str(prom_path), "--wait", "--timeout", "4m"), flush=True)
print("Updating existing Grafana; retaining RED and datasource configuration", flush=True)
print(helm("upgrade", "grafana", "grafana/grafana", "--version", "10.5.15", "-n", "monitoring",
           "--reuse-values", "-f", str(graf_path), "--wait", "--timeout", "4m"), flush=True)
print("PASS: existing releases updated from shop CRs; dashboard UID=shop-platform", flush=True)
