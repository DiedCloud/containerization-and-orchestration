"""Trigger ShopPolicyDrops with denied stranger -> PostgreSQL attempts."""
import argparse
import json
import subprocess

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--duration', type=int, default=150)
a = p.parse_args()
ip = json.loads(subprocess.check_output(['kubectl','-n','shop','get','svc','shop-postgres-rw','-o','json']))['spec']['clusterIP']
code = '''import socket,time
end=time.monotonic()+DURATION
blocked=0
while time.monotonic()<end:
 try:
  socket.create_connection((ADDRESS,5432),timeout=.4).close()
  raise RuntimeError('Unexpected PostgreSQL access from stranger')
 except OSError:blocked+=1
 time.sleep(.1)
print('Denied PostgreSQL connection attempts:',blocked)
'''.replace('DURATION',str(a.duration)).replace('ADDRESS',repr(ip))
subprocess.run(['kubectl','-n','shop','exec','-i','deployment/shop-stranger','--','python','-'],input=code,text=True,check=True)
