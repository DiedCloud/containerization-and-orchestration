"""Count /version responses, including a binomial uncertainty interval."""
import collections,json,math,subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1]
result=subprocess.check_output(['kubectl','-n','shop6','exec','-i','deploy/shop-client','-c','client','--','python','-','--seconds','50','--rate','40','--path','/version'],input=(root/'scripts/load.py').read_bytes())
rows=[json.loads(x) for x in result.splitlines()]
counts=collections.Counter(r['version'] for r in rows)
n=len(rows);p=counts['v2']/n
summary={'n':n,'counts':dict(counts),'v2_fraction':p,'expected_v2':.1,'approx_95pct_half_width':1.96*math.sqrt(.1*.9/n), 'errors':sum(r['code']!=200 for r in rows)}
(root/'evidence/versions.json').write_text(json.dumps(summary,indent=2))
print(json.dumps(summary,indent=2))
assert summary['errors']==0 and abs(p-.1) < 4*math.sqrt(.1*.9/n)
