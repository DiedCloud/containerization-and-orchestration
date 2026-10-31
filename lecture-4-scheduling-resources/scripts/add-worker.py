"""Join one kind worker without recreating the Lab 2/3 cluster."""
import json
import subprocess
import time


def run(*args, data=None):
    return subprocess.check_output(args, input=data, text=True).strip()


control, worker = "lab2-control-plane", "lab2-worker"
image = run("docker", "inspect", control, "--format", "{{.Config.Image}}")
if worker not in run("docker", "ps", "-a", "--format", "{{.Names}}").splitlines():
    run("docker", "run", "-d", "--name", worker, "--hostname", worker,
        "--label", "io.x-k8s.kind.cluster=lab2", "--label", "io.x-k8s.kind.role=worker",
        "--privileged", "--security-opt", "seccomp=unconfined", "--security-opt", "apparmor=unconfined",
        "--network", "kind", "--cgroupns=private", "--tmpfs", "/tmp", "--tmpfs", "/run",
        "--volume", "/var", "--volume", "/lib/modules:/lib/modules:ro", image)
    for _ in range(60):
        if subprocess.run(["docker", "exec", worker, "test", "-S", "/run/containerd/containerd.sock"]).returncode == 0:
            break
        time.sleep(1)
if worker not in run("kubectl", "--context", "kind-lab2", "get", "nodes", "-o", "name"):
    # Bootstrap token exists only in process memory and the node's temporary file.
    token = run("docker", "exec", control, "kubeadm", "token", "create", "--ttl", "15m")
    ip = run("docker", "inspect", worker, "--format", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}")
    config = {"apiVersion": "kubeadm.k8s.io/v1beta4", "kind": "JoinConfiguration",
              "discovery": {"bootstrapToken": {"apiServerEndpoint": control + ":6443", "token": token,
                                               "unsafeSkipCAVerification": True}},
              "nodeRegistration": {"criSocket": "unix:///run/containerd/containerd.sock", "kubeletExtraArgs": [
                  {"name": "node-ip", "value": ip},
                  {"name": "provider-id", "value": "kind://docker/lab2/" + worker}]},
              "skipPhases": ["preflight"]}
    run("docker", "exec", "-i", worker, "cp", "/dev/stdin", "/tmp/join.json", data=json.dumps(config))
    print(run("docker", "exec", worker, "kubeadm", "join", "--config", "/tmp/join.json"))
    run("docker", "exec", worker, "rm", "/tmp/join.json")
print(run("kubectl", "--context", "kind-lab2", "wait", "--for=condition=Ready", "node/" + worker, "--timeout=120s"))
