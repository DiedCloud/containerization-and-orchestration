"""Translate this lab's monitoring CRs into the existing Lab 2 Helm releases.

This is an explicit one-shot adapter, not Prometheus Operator. Supported:
ServiceMonitor matchLabels, matchNames, HTTP endpoints; PrometheusRule groups.
Generated overrides/evidence remain local. Run again after CR changes.
"""
import argparse
import base64
import copy
import json
from pathlib import Path
import re
import subprocess
import time
import urllib.parse

from monitoring_api import service_api
from monitoring_config import dashboard_overrides, merge_rules, merge_scrapes


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
# Back up previous release values without printing credentials.
(args.output / "prometheus-before.json").write_text(json.dumps(prometheus, indent=2))
(args.output / "grafana-before.json").write_text(json.dumps(grafana, indent=2))
monitors = json.loads(kube("get", "servicemonitor", "-n", "shop", "-l", "app.kubernetes.io/instance=shop", "-o", "json"))["items"]
rules = json.loads(kube("get", "prometheusrule", "-n", "shop", "-l", "app.kubernetes.io/instance=shop", "-o", "json"))["items"]
assert (len(monitors), len(rules)) in {(2, 1), (3, 1), (0, 0)}, "Incomplete shop monitoring objects"
dashboard_enabled = bool(kube("get", "configmap", "shop-dashboard", "-n", "monitoring", "--ignore-not-found", "-o", "name").strip())
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

scrapes = merge_scrapes(prometheus.get("extraScrapeConfigs", ""), jobs)
old_groups = prometheus.get("serverFiles", {}).get("alerting_rules.yml", {}).get("groups", [])
groups, new_groups = merge_rules(old_groups, rules)
assert sum(len(g["rules"]) for g in new_groups) == (3 if rules else 0)
check = kube("exec", "-i", "-n", "monitoring", "deployment/prometheus-server", "-c", "prometheus-server", "--",
             "/bin/promtool", "check", "rules", "/dev/stdin", data=json.dumps({"groups": new_groups}))
print(check, end="", flush=True)
prom_override = {"extraScrapeConfigs": scrapes, "serverFiles": {"alerting_rules.yml": {"groups": groups}}}
prom_path = args.output / "prometheus-overrides.json"
prom_path.write_text(json.dumps(prom_override, indent=2, ensure_ascii=False))
graf_override = dashboard_overrides(grafana, dashboard_enabled)
graf_path = args.output / "grafana-overrides.json"
graf_path.write_text(json.dumps(graf_override, indent=2))
print(f"Read {len(monitors)} ServiceMonitor and {len(rules)} PrometheusRule: {len(jobs)} jobs, {sum(len(g['rules']) for g in new_groups)} alerts", flush=True)
if any(prometheus.get(key) != value for key, value in prom_override.items()):
    print("Updating existing Prometheus; retaining Lab 2 jobs, rules and Alertmanager", flush=True)
    print(helm("upgrade", "prometheus", "prometheus-community/prometheus", "--version", "29.38.1", "-n", "monitoring",
               "--reuse-values", "-f", str(prom_path), "--wait", "--timeout", "4m"), flush=True)
else:
    print("Prometheus overrides already match shop CRs", flush=True)
if any(grafana.get(key) != value for key, value in graf_override.items()):
    print("Updating existing Grafana; retaining RED and datasource configuration", flush=True)
    print(helm("upgrade", "grafana", "grafana/grafana", "--version", "10.5.15", "-n", "monitoring",
               "--reuse-values", "-f", str(graf_path), "--wait", "--timeout", "4m"), flush=True)
else:
    print("Grafana provisioning already matches shop", flush=True)


def seconds(duration):
    units = {"ms": 0.001, "s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800, "y": 31536000}
    pieces = re.findall(r"(\d+)(ms|s|m|h|d|w|y)", str(duration))
    assert pieces and "".join(n + u for n, u in pieces) == str(duration), "Unsupported duration"
    return sum(int(n) * units[u] for n, u in pieces)


def rule_signature(rule, loaded=False):
    return (rule["name" if loaded else "alert"], re.sub(r"\s+", "", rule["query" if loaded else "expr"]),
            float(rule["duration"]) if loaded else seconds(rule.get("for", "0s")),
            rule.get("labels", {}), rule.get("annotations", {}))


# Helm --wait cannot prove Prometheus reloaded a ConfigMap. Verify the running
# server, including expression/labels/duration, rather than only Helm values.
with service_api(args.context, "prometheus-server") as prometheus_api:
    formatted_groups = copy.deepcopy(new_groups)
    for group in formatted_groups:
        for rule in group["rules"]:
            rule["expr"] = prometheus_api("/api/v1/format_query?" + urllib.parse.urlencode({"query": rule["expr"]}))["data"]
    expected = {g["name"]: [rule_signature(r) for r in g["rules"]] for g in formatted_groups}
    deadline = time.monotonic() + 120
    while True:
        try:
            config = prometheus_api("/api/v1/status/config")["data"]["yaml"]
            loaded_jobs = set(re.findall(r"^\s*-?\s*job_name: [\"']?([^\n\"']+)", config, re.M))
            owned_jobs = {name for name in loaded_jobs if name.startswith("serviceMonitor/shop/")}
            loaded_groups = prometheus_api("/api/v1/rules")["data"]["groups"]
            actual = {g["name"]: [rule_signature(r, loaded=True) for r in g["rules"]]
                      for g in loaded_groups if g["name"].startswith("shop-cr/")}
            if owned_jobs == {j["job_name"] for j in jobs} and actual == expected:
                break
        except (OSError, ValueError, KeyError):
            pass
        if time.monotonic() > deadline:
            raise RuntimeError("Prometheus did not load the shop scrape jobs/rule definitions within 120s")
        time.sleep(2)
if dashboard_enabled:
    secret = json.loads(kube("get", "secret", "grafana", "-n", "monitoring", "-o", "json"))["data"]
    credentials = base64.b64decode(secret["admin-user"]) + b":" + base64.b64decode(secret["admin-password"])
    authorization = "Basic " + base64.b64encode(credentials).decode()
    expected_dashboard = json.loads(json.loads(kube("get", "configmap", "shop-dashboard", "-n", "monitoring", "-o", "json"))["data"]["shop.json"])
    with service_api(args.context, "grafana") as grafana_api:
        deadline = time.monotonic() + 120
        while True:
            try:
                dashboard = grafana_api("/api/dashboards/uid/" + expected_dashboard["uid"], authorization)
                if dashboard["meta"]["provisioned"] and dashboard["dashboard"]["panels"] == expected_dashboard["panels"]:
                    break
            except (OSError, ValueError, KeyError):
                pass
            if time.monotonic() > deadline:
                raise RuntimeError("Grafana did not provision the shop dashboard within 120s")
            time.sleep(2)
print("PASS: running Prometheus matches shop CRs; Grafana provisioning verified", flush=True)
