"""Persist actual Prometheus alert state; fail unless requested alert is firing."""
import argparse
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'lecture-3-kubernetes-control-plane/scripts'))
from monitoring_api import service_api
parser=argparse.ArgumentParser()
parser.add_argument('alert')
parser.add_argument('--timeout',type=int,default=150)
args=parser.parse_args()
with service_api('kind-lab2','prometheus-server') as get:
    deadline=time.monotonic()+args.timeout
    while True:
        result=get('/api/v1/alerts')
        if any(a['labels'].get('alertname')==args.alert and a['state']=='firing' for a in result['data']['alerts']):
            p=Path(__file__).resolve().parents[1]/'evidence'/('09-'+args.alert+'-firing.json')
            p.write_text(json.dumps({'captured_at':time.time(),'response':result},indent=2,ensure_ascii=False)+'\n')
            print('FIRING:',args.alert,flush=True)
            break
        if time.monotonic()>deadline:raise RuntimeError('Alert never fired: '+args.alert)
        time.sleep(3)
