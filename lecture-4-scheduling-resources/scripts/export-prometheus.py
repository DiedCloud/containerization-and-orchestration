"""Save actual dashboard ranges, using a fresh temporary service port-forward."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
import urllib.parse

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root.parent/'lecture-3-kubernetes-control-plane/scripts'))
from monitoring_api import service_api
parser=argparse.ArgumentParser()
parser.add_argument('--start',type=float,default=None)
parser.add_argument('--end',type=float,default=time.time())
args=parser.parse_args()
if args.start is None:
    args.start=json.loads((root/'evidence/phases.json').read_text())[0]['time']-60
dashboard=json.loads((root/'shop/dashboards/shop.json').read_text())
result={'captured':datetime.now(timezone.utc).isoformat(),'start':args.start,'end':args.end,'panels':[]}
with service_api('kind-lab2','prometheus-server') as get:
    for panel in dashboard['panels']:
        query=panel['targets'][0]['expr']
        data=get('/api/v1/query_range?'+urllib.parse.urlencode({'query':query,'start':args.start,'end':args.end,'step':15}))
        if data['status']!='success':raise RuntimeError(data)
        result['panels'].append({'title':panel['title'],'query':query,'response':data})
(root/'evidence/09-prometheus-ranges.json').write_text(json.dumps(result,indent=2)+'\n')
print('Saved',len(result['panels']),'actual Prometheus query ranges')
