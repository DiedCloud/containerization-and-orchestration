"""Read-only CloudNativePG discovery adapter for upstream KRR v1.31.1.

Run from the upstream KRR checkout, after installing its requirements.
No fake Kubernetes resources are created; only KRR discovery is extended.
The metric loaders, strategy, rounding and report generation are unchanged.
"""
from pathlib import Path
import sys

source = Path.cwd()
model = source / "robusta_krr/core/models/objects.py"
text = model.read_text()
if '    "Cluster",' not in text:
    model.write_text(text.replace('KindLiteral = Literal[', 'KindLiteral = Literal[\n    "Cluster",'))
sys.path.insert(0, str(source))
from types import SimpleNamespace
from robusta_krr.core.integrations.kubernetes import ClusterLoader
from robusta_krr.core.models.objects import K8sObjectData
from robusta_krr.core.models.allocations import ResourceAllocations
from robusta_krr import run

original = ClusterLoader.list_scannable_objects


async def with_cnpg(self):
    objects = await original(self)
    if not self._should_list_resource("Cluster"):
        return objects
    namespaces = self.namespaces
    if namespaces == "*":
        clusters = self.custom_objects.list_cluster_custom_object("postgresql.cnpg.io", "v1", "clusters")["items"]
    else:
        clusters = [c for ns in namespaces for c in self.custom_objects.list_namespaced_custom_object(
            "postgresql.cnpg.io", "v1", ns, "clusters")["items"]]
    for cluster in clusters:
        meta = cluster["metadata"]
        selector = {"cnpg.io/cluster": meta["name"]}
        pods = self.core.list_namespaced_pod(meta["namespace"], label_selector="cnpg.io/cluster=" + meta["name"]).items
        if not pods:
            continue
        container = next(c for c in pods[0].spec.containers if c.name == "postgres")
        obj = K8sObjectData(cluster=self.cluster, namespace=meta["namespace"], name=meta["name"],
                            kind="Cluster", container=container.name, hpa=None,
                            allocations=ResourceAllocations.from_container(container),
                            labels=meta.get("labels", {}), annotations={})
        obj._api_resource = SimpleNamespace(metadata=SimpleNamespace(namespace=meta["namespace"]),
                                            spec=SimpleNamespace(selector=SimpleNamespace(match_labels=selector, match_expressions=None)))
        objects.append(obj)
    return objects


ClusterLoader.list_scannable_objects = with_cnpg
if __name__ == "__main__":
    run()
