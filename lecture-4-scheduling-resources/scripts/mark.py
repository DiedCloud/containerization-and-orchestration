import json
from pathlib import Path
import sys
import time
p=Path(__file__).resolve().parents[1]/'evidence/phases.json'
rows=json.loads(p.read_text()) if p.exists() else []
rows.append({'phase':sys.argv[1], 'time':time.time()})
p.write_text(json.dumps(rows,indent=2)+'\n')
print(rows[-1])
