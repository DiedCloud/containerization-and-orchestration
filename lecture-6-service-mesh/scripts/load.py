"""Fixed-rate order workload, no HTTP retries; run inside shop-client."""
import argparse
import json
import time
import urllib.request
import urllib.error
p=argparse.ArgumentParser()
p.add_argument('--seconds',type=int,default=180)
p.add_argument('--rate',type=float,default=20)
p.add_argument('--path',default='/order')
a=p.parse_args()
start=time.monotonic()
for i in range(int(a.seconds*a.rate)):
    time.sleep(max(0,start+i/a.rate-time.monotonic()))
    req=urllib.request.Request('http://shop-api:8000'+a.path,
        data=b'{"item":"mesh-test","quantity":1}' if a.path=='/order' else None,
        headers={'Content-Type':'application/json'})
    t=time.monotonic()
    try:
        with urllib.request.urlopen(req,timeout=3) as r:
            code,body=r.status,r.read().decode()
    except urllib.error.HTTPError as e:
        code,body=e.code,e.read().decode()
    except Exception as e:
        code,body=0,str(e)
    print(json.dumps({'time':time.time(),'ms':(time.monotonic()-t)*1000,'code':code,
                      'version':body if a.path=='/version' else None}),flush=True)
