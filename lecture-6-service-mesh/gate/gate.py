"""Prometheus-driven canary gate; HTTPRoute is the only object it can patch."""
import json
import math
import os
import ssl
import time
import urllib.parse
import urllib.request

PROM = os.getenv('PROMETHEUS_URL', 'http://prometheus-server.monitoring.svc.cluster.local')
NS = os.getenv('NAMESPACE', 'shop6')
TOKEN = '/var/run/secrets/kubernetes.io/serviceaccount/token'
CA = '/var/run/secrets/kubernetes.io/serviceaccount/ca.crt'
BASE = f'https://kubernetes.default.svc/apis/policy.linkerd.io/v1beta2/namespaces/{NS}/httproutes/shop-api'
SELECTOR = 'namespace="shop6",direction="inbound",deployment="shop-api-v2"'

def query(expr):
    data = json.load(urllib.request.urlopen(PROM + '/api/v1/query?' + urllib.parse.urlencode({'query':expr}), timeout=5))
    if data['status'] != 'success':
        raise RuntimeError('Prometheus query failed')
    result = data['data']['result']
    return float(result[0]['value'][1]) if len(result) == 1 else float('nan')

def kube(method='GET', data=None):
    req = urllib.request.Request(BASE, data=None if data is None else json.dumps(data).encode(), method=method,
        headers={'Authorization':'Bearer '+open(TOKEN).read().strip(), 'Content-Type':'application/merge-patch+json'})
    return json.load(urllib.request.urlopen(req, context=ssl.create_default_context(cafile=CA), timeout=5))

def main():
    good = 0
    # Each fresh rollout needs an explicit gate restart; no stale window can promote it.
    time.sleep(65)
    while True:
        try:
            route = kube()
            refs = route['spec']['rules'][0]['backendRefs']
            weight = refs[1]['weight']
            total = query(f'sum(increase(response_total{{{SELECTOR}}}[1m]))')
            failed = query(f'sum(increase(response_total{{{SELECTOR},status_code=~"5.."}}[1m])) or vector(0)')
            p95 = query(f'histogram_quantile(0.95,sum by(le)(rate(response_latency_ms_bucket{{{SELECTOR}}}[1m])))')
            valid = all(math.isfinite(x) for x in [total,failed,p95]) and total >= 30
            error = failed / total if valid else None
            decision = 'hold'
            if valid and (error > 0.05 or p95 > 250):
                target, good, decision = 0, 0, 'rollback'
            elif valid:
                good += 1
                target = min(100,weight+30) if good >= 2 else weight
                if target != weight:
                    good, decision = 0, 'promote'
            else:
                target, good = weight, 0
            if decision in ['rollback','promote']:
                refs[0]['weight'], refs[1]['weight'] = 100-target,target
                rules = route['spec']['rules']
                # Optimistic concurrency: do not overwrite a concurrent Helm rollout.
                kube('PATCH', {'metadata':{'resourceVersion':route['metadata']['resourceVersion']}, 'spec':{'rules':rules}})
            else:
                target = weight
            print(json.dumps({'time':time.time(),'weight':weight,'target':target,'requests':total,
                              'error':error,'p95_ms':p95,'decision':decision}),flush=True)
            if target in [0,100]:
                return
        except Exception as exc:
            good = 0
            print(json.dumps({'time':time.time(),'decision':'hold','reason':str(exc)}),flush=True)
        time.sleep(15)

if __name__ == '__main__':
    main()
