"""Leave less CPU headroom than one API request on each node.

All workloads still change through Helm. Only kubelet system reservations
are changed here to make a 16-core desktop a deliberately tight lab platform.
"""
import json
from pathlib import Path
import subprocess
from decimal import Decimal
import time

root = Path(__file__).resolve().parents[1]
def kube(*args):
    return json.loads(subprocess.check_output(['kubectl', '--context', 'kind-lab2', *args, '-o', 'json']))
def cpu(quantity):
    return Decimal(quantity[:-1]) / 1000 if quantity.endswith('m') else Decimal(quantity)
nodes = kube('get', 'nodes')['items']
pods = kube('get', 'pods', '-A')['items']
api = next(p for p in pods if p['metadata']['namespace']=='shop' and p['metadata']['labels'].get('app.kubernetes.io/name')=='api')
request = sum(cpu(c['resources']['requests']['cpu']) for c in api['spec']['containers'])
reservations = {}
for node in nodes:
    name=node['metadata']['name']
    assigned=[p for p in pods if p['spec'].get('nodeName')==name and p['status']['phase'] not in ('Succeeded','Failed') and p['metadata'].get('labels',{}).get('app')!='shop-batch']
    total=Decimal(0)
    for pod in assigned:
        regular=sum(cpu(c.get('resources',{}).get('requests',{}).get('cpu','0')) for c in pod['spec']['containers'])
        init=max([cpu(c.get('resources',{}).get('requests',{}).get('cpu','0')) for c in pod['spec'].get('initContainers',[])] or [Decimal(0)])
        total+=max(regular,init)
    target=total+Decimal('1')+request/2 # exactly two 500m batch pods per node
    reserved=cpu(node['status']['capacity']['cpu'])-target
    quantity=f'{int(reserved*1000)}m'
    subprocess.run(['python3',str(root/'scripts/node-resources.py'),'--node',name,'--reserved-cpu',quantity],check=True)
    reservations[name]={'existing_requests_cpu':str(total),'api_request_cpu':str(request),'batch_slots':2,'reserved_cpu':quantity,'target_allocatable_cpu':str(target)}
(root/'evidence/06-capacity.json').write_text(json.dumps(reservations,indent=2)+'\n')

# Do not start filling while the scheduler still sees the previous capacity.
for _ in range(45):
    current=kube('get','nodes')['items']
    if all(abs(cpu(n['status']['allocatable']['cpu']) - Decimal(reservations[n['metadata']['name']]['target_allocatable_cpu'])) < Decimal('0.002') for n in current):
        print('Scheduler sees constrained allocatable on both nodes')
        break
    time.sleep(1)
else:
    raise RuntimeError('Node allocatable did not converge')
