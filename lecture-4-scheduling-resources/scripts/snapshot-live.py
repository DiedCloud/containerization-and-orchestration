"""Save compact live invariants, including critical Pod identity and restarts."""
import json
from pathlib import Path
import subprocess
import sys
import time
root=Path(__file__).resolve().parents[1]
pods=json.loads(subprocess.check_output(['kubectl','--context','kind-lab2','-n','shop','get','pods','-o','json']))['items']
rows=[]
for p in pods:
    rows.append({'name':p['metadata']['name'],'uid':p['metadata']['uid'],'component':p['metadata']['labels'].get('app.kubernetes.io/name'),
                 'node':p['spec'].get('nodeName'),'qos':p['status'].get('qosClass'),'priority':p['spec'].get('priority'),
                 'phase':p['status']['phase'],'reason':p['status'].get('reason'),
                 'restarts':sum(c['restartCount'] for c in p['status'].get('containerStatuses',[])),
                 'ready':all(c.get('ready',False) for c in p['status'].get('containerStatuses',[])) and bool(p['status'].get('containerStatuses')),
                 'resources':{c['name']:c.get('resources',{}) for c in p['spec']['containers']}})
(root/'evidence'/f'{sys.argv[1]}.json').write_text(json.dumps({'time':time.time(),'pods':rows},indent=2)+'\n')
