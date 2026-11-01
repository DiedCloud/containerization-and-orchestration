"""Probe every source role against API, worker, PostgreSQL and DNS."""
import argparse
import json
import subprocess
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--output', type=Path, default=Path('results/matrix.json'))
a = p.parse_args()
def kube(*args):
    return json.loads(subprocess.check_output(['kubectl', '-n', 'shop', *args, '-o', 'json']))
pods = kube('get', 'pods')['items']
roles = {}
for role in ['client', 'api', 'worker', 'postgres', 'stranger']:
    selected = [x for x in pods if x['metadata']['labels'].get('app.kubernetes.io/name') == role
                and x['status'].get('phase') == 'Running' and not x['metadata'].get('deletionTimestamp')]
    if role == 'postgres':
        selected = [x for x in pods if x['metadata']['labels'].get('cnpg.io/cluster') == 'shop-postgres'
                    and x['status'].get('phase') == 'Running']
    roles[role] = selected
services = {role: kube('get', 'svc', name)['spec']['clusterIP'] for role, name in
            [('api', 'shop-api'), ('worker', 'shop-worker'), ('postgres', 'shop-postgres-rw')]}
dns_ip = json.loads(subprocess.check_output(['kubectl','-n','kube-system','get','svc','kube-dns','-o','json']))['spec']['clusterIP']
rows = []
for source, selected in roles.items():
  for source_pod in selected:
    pod = source_pod['metadata']['name']
    for target, ip in services.items():
        if target == source:
            if source == 'postgres':
                ip = '127.0.0.1'
            else:
                ip = next(x['status']['podIP'] for x in selected if x['metadata']['name'] != pod)
        port = 5432 if target == 'postgres' else 8000
        expected = (source, target) in [('client', 'api'), ('api', 'postgres'), ('worker', 'postgres'), ('postgres', 'postgres')]
        code = f'''import socket,json
try:
 s=socket.create_connection(({ip!r},{port}),timeout=1);s.close();print(json.dumps(True))
except OSError:print(json.dumps(False))'''
        # CNPG has no Python; use bash /dev/tcp through timeout instead.
        if source == 'postgres':
            r = subprocess.run(['kubectl', '-n', 'shop', 'exec', pod, '--', 'bash', '-c',
                f'timeout 1 bash -c "exec 3<>/dev/tcp/{ip}/{port}"'], capture_output=True)
            actual = r.returncode == 0
        else:
            r = subprocess.run(['kubectl', '-n', 'shop', 'exec', pod, '--', 'python3', '-c', code], capture_output=True, text=True)
            if r.returncode: raise RuntimeError(r.stderr)
            actual = json.loads(r.stdout)
        rows.append(dict(source=source, pod=pod, address=ip, target=target, port=port, expected=expected, actual=actual, match=expected==actual))
    if source != 'postgres':
        code = f'import socket; print(socket.gethostbyname("shop-api.shop.svc.cluster.local")); socket.create_connection(({dns_ip!r},53),timeout=1).close()'
    else:
        code = None
    if code:
        r = subprocess.run(['kubectl','-n','shop','exec',pod,'--','python','-c',code], capture_output=True, timeout=30)
    else:
        r = subprocess.run(['kubectl','-n','shop','exec',pod,'--','bash','-c',f'getent hosts shop-api.shop.svc.cluster.local && timeout 1 bash -c "exec 3<>/dev/tcp/{dns_ip}/53"'], capture_output=True, timeout=30)
    actual = r.returncode == 0
    rows.append(dict(source=source,pod=pod,target='DNS',port=53,expected=True,actual=actual,match=actual))
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps(rows,indent=2)+'\n')
print('| Источник / Pod | Адресат | Ожидаемо | Фактически | Совпало |')
print('|---|---|---|---|---|')
for r in rows:
    print(f"| {r['source']} / {r['pod']} | {r['target']}:{r['port']} | {'allow' if r['expected'] else 'deny'} | {'allow' if r['actual'] else 'deny'} | {'✓' if r['match'] else 'FAIL'} |")
raise SystemExit(0 if all(r['match'] for r in rows) else 1)
