"""Resource cost outside API pods, at the same timestamp as the mesh comparison."""
import json
from pathlib import Path
from prom import query
r=Path(__file__).resolve().parents[1]
end=json.loads((r/'evidence/mesh.json').read_text())['end']
result={}
for label,selector in [('control_plane','namespace="linkerd",container!="",container!="POD",image!=""'),('client_proxy','namespace="shop6",pod=~"shop-client-.*",container="linkerd-proxy"')]:
    result[label]={'cpu_cores':query(f'sum(rate(container_cpu_usage_seconds_total{{{selector}}}[119s]))',end),
                   'memory_bytes':query(f'sum(avg_over_time(container_memory_working_set_bytes{{{selector}}}[119s]))',end)}
(r/'evidence/overhead.json').write_text(json.dumps(result,indent=2))
