"""Admission integration checks. Invalid raw manifests must actually be rejected.

Run with python3 policies/verify.py from any working directory.
No accepted Pod is persisted: all positive and extended checks use server dry-run.
"""
import copy
import json
import os
from pathlib import Path
import subprocess


HERE = Path(__file__).resolve().parent
CONTEXT = os.getenv("KUBE_CONTEXT", "kind-lab2")
RULES = {
    "01-no-limits.yaml": "require-resource-limits",
    "02-untrusted-image.yaml": "trusted-image-sources",
    "03-no-label.yaml": "require-app-label",
    "04-privileged.yaml": "disallow-privileged",
    "05-host-network.yaml": "disallow-host-namespaces",
}


def kubectl(*args, data=None):
    return subprocess.run(
        ["kubectl", "--context", CONTEXT, "--request-timeout=30s", *args],
        input=data, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )


def verify(result, expected=None):
    print(result.stdout.strip(), flush=True)
    if expected is None:
        assert result.returncode == 0, "A compliant manifest was rejected"
    else:
        assert result.returncode != 0, "An invalid manifest was accepted"
        assert "platform-guardrails" in result.stdout, "Failure was not caused by our policy"
        assert expected in result.stdout, f"Expected rejection by {expected}"
        for other in set(RULES.values()) - {expected}:
            assert other not in result.stdout, f"Unexpected additional failing rule: {other}"


print(f"Context: {CONTEXT}", flush=True)
for filename, rule in RULES.items():
    print(f"\n=== {filename}: expect {rule} ===", flush=True)
    verify(kubectl("create", "-f", str(HERE / "examples" / filename)), rule)

print("\n=== Compliant Pod: expect admission ===", flush=True)
verify(kubectl("create", "--dry-run=server", "-f", str(HERE / "examples/valid.yaml")))

baseline_result = kubectl("create", "--dry-run=client", "-f", str(HERE / "examples/valid.yaml"), "-o", "json")
assert baseline_result.returncode == 0, baseline_result.stdout
baseline = json.loads(baseline_result.stdout)


def check_object(label, obj, expected=None):
    print(f"\n=== {label} ===", flush=True)
    verify(kubectl("create", "--dry-run=server", "-f", "-", data=json.dumps(obj)), expected)


short = copy.deepcopy(baseline)
short["metadata"]["namespace"] = "default"
short["spec"]["containers"][0]["image"] = "shop:1.0.0"
check_object("Short image name + default namespace: expect admission", short)
short["spec"]["containers"][0]["image"] = "quay.io/untrusted/shop:1.0.0"
check_object("Foreign image in default: expect rejection outside shop too", short, "trusted-image-sources")
for image in ("docker.io/untrusted/shop:1.0.0", "docker.io/library.evil/shop:1.0.0"):
    short["spec"]["containers"][0]["image"] = image
    check_object(f"{image}: expect rejection", short, "trusted-image-sources")

operator_image = copy.deepcopy(baseline)
operator_image["spec"]["containers"][0]["image"] = "ghcr.io/cloudnative-pg/postgresql:17.7"
check_object("CloudNativePG image: expect admission", operator_image)

for field in ("hostPID", "hostIPC"):
    host = copy.deepcopy(baseline)
    host["spec"][field] = True
    check_object(f"{field}: expect rejection", host, "disallow-host-namespaces")

init = copy.deepcopy(baseline)
init_container = copy.deepcopy(init["spec"]["containers"][0])
init_container["name"] = "init"
init_container["image"] = "quay.io/untrusted/init:1.0.0"
init["spec"]["initContainers"] = [init_container]
check_object("Untrusted initContainer: expect rejection", init, "trusted-image-sources")
init_container["image"] = "docker.io/library/shop:1.0.0"
init_container.pop("resources")
check_object("InitContainer without limits: expect rejection", init, "require-resource-limits")
init_container["resources"] = {"limits": {"cpu": "100m", "memory": "128Mi"}}
init_container["securityContext"]["privileged"] = True
check_object("Privileged initContainer: expect rejection", init, "disallow-privileged")

deployment = {
    "apiVersion": "apps/v1",
    "kind": "Deployment",
    "metadata": {"name": "guardrail-deployment", "namespace": "shop"},
    "spec": {
        "replicas": 1,
        "selector": {"matchLabels": {"app": "policy-check"}},
        "template": {
            "metadata": {"labels": {"app": "policy-check"}},
            "spec": copy.deepcopy(baseline["spec"]),
        },
    },
}
deployment["spec"]["template"]["spec"].pop("restartPolicy")
check_object("Compliant Deployment: expect admission", deployment)
deployment["spec"]["template"]["spec"]["containers"][0].pop("resources")
check_object("Deployment without limits: expect autogen rejection", deployment, "require-resource-limits")

print("\nPASS: 5 raw rejections + 13 admission checks; no test Pods created", flush=True)
