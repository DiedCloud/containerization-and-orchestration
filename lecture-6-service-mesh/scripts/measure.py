"""Summarize real client samples and corresponding cAdvisor resource window."""
import argparse,json,math,urllib.parse,urllib.request
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument('input',type=Path)
p.add_argument('output',type=Path)
a=p.parse_args()
rows=[json.loads(x) for x in a.input.read_text().splitlines()]
lat=sorted(r['ms'] for r in rows)
end=rows[-1]['time']; seconds=int(end-rows[0]['time'])
def query(expr):
    url='http://localhost:19090/api/v1/query?'+urllib.parse.urlencode({'query':expr,'time':end})
    result=json.load(urllib.request.urlopen(url))['data']['result']
    return [{'labels':x['metric'],'value':float(x['value'][1])} for x in result]
selector='namespace="shop6",pod=~"shop-api-v1-.*",container=~"api|linkerd-proxy"'
result={'start':rows[0]['time'],'end':end,'requests':len(rows),'errors':sum(r['code']!=201 for r in rows),
        'mean_ms':sum(lat)/len(lat),'p50_ms':lat[int(len(lat)*.5)],'p95_ms':lat[int(len(lat)*.95)],
        'cpu_cores':query(f'sum by(container)(rate(container_cpu_usage_seconds_total{{{selector}}}[{seconds}s]))'),
        'memory_bytes':query(f'sum by(container)(avg_over_time(container_memory_working_set_bytes{{{selector}}}[{seconds}s]))')}
a.output.write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
