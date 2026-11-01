"""Small Prometheus HTTP API helper, also used to export graph data."""
import json,urllib.parse,urllib.request
URL='http://localhost:19090'
def query(expr,at=None):
    params={'query':expr}
    if at: params['time']=at
    return json.load(urllib.request.urlopen(URL+'/api/v1/query?'+urllib.parse.urlencode(params)))['data']['result']
def series(expr,start,end,step=5):
    return json.load(urllib.request.urlopen(URL+'/api/v1/query_range?'+urllib.parse.urlencode({'query':expr,'start':start,'end':end,'step':step})))['data']['result']
