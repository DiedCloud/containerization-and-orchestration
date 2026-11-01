from pathlib import Path
import json
from prom import query,series
r=Path(__file__).resolve().parents[1]
rows=[json.loads(x) for x in Path('/tmp/lab6-flaky.jsonl').read_text().splitlines()]
start,end=rows[0]['time'],rows[-1]['time']
sel='namespace="shop6",direction="inbound",deployment="shop-api-v1",target_port="8000",route_name!="probe"'
expr=f'sum(rate(response_total{{{sel},status_code=~"5.."}}[30s])) / sum(rate(response_total{{{sel}}}[30s]))'
retry='sum(increase(outbound_http_route_retry_requests_total{namespace="shop6",route_name="shop-api"}[%ds]))'%int(end-start)
success=retry.replace('retry_requests','retry_successes')
result={'start':start,'end':end,'requests':len(rows),'errors':sum(x['code']!=201 for x in rows),
        'backend_error_series':series(expr,start,end),'retry_requests':query(retry,end),'retry_successes':query(success,end),
        'retry_overflow':query(retry.replace('retry_requests','retry_overflow'),end),'client_windows':[]}
for t in range(0,int(end-start),10):
    subset=[x for x in rows if start+t <= x['time'] < start+t+10]
    if subset: result['client_windows'].append([start+t,sum(x['code']!=201 for x in subset)/len(subset)])
(r/'evidence/flaky.json').write_text(json.dumps(result,indent=2))
print('Requests:',result['requests'],'client errors:',result['errors'])
print('Retry requests:',result['retry_requests'],'successes:',result['retry_successes'])
