"""Create only this experiment's bounded private fixture from existing server images."""
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
NETWORK = 'new-api-sm-20260905'


def main():
    os.umask(0o077)
    names = ['new-api-cloud-new-api-1', 'new-api-cloud-redis-1', 'new-api-cloud-nginx-1', 'new-api-cloud-mysql-1']
    originals = json.loads(subprocess.check_output(['docker', 'inspect', *names]))
    if any(not c['State']['Running'] or c['State']['OOMKilled'] for c in originals):
        raise RuntimeError('original service guard failed')
    existing = subprocess.check_output(['docker', 'ps', '-a', '--format', '{{.Names}}'], text=True).splitlines()
    if any(n in existing for n in ['new-api-sm-app', 'new-api-sm-redis', 'new-api-sm-nginx']) or (ROOT/'data').exists():
        raise RuntimeError('refusing to overwrite existing fixture')
    (ROOT/'data').mkdir()
    (ROOT/'results').mkdir(exist_ok=True)
    (ROOT/'nginx.conf').write_text("""worker_processes 1;
events { worker_connections 1024; }
http {
  access_log off;
  server {
    listen 80;
    client_max_body_size 2m;
    location / {
      proxy_pass http://new-api-sm-app:3000;
      proxy_http_version 1.1;
      proxy_set_header Connection "";
      proxy_buffering off;
      proxy_request_buffering off;
      proxy_read_timeout 20s;
      proxy_send_timeout 20s;
    }
  }
}
""")
    subprocess.run(['docker','network','create','--internal','--subnet','172.19.0.0/16','--gateway','172.19.0.1',NETWORK],check=True)
    common = ['docker','run','-d','--network',NETWORK,'--log-opt','max-size=5m','--log-opt','max-file=1']
    subprocess.run(common + ['--name','new-api-sm-redis','--ip','172.19.0.2','--memory','64m','--cpus','0.1','--pids-limit','64',originals[1]['Image'],'redis-server','--save','','--appendonly','no','--maxmemory','32mb','--maxmemory-policy','noeviction'],check=True)
    env = {'SQLITE_PATH':'/data/bench.db','REDIS_CONN_STRING':'redis://new-api-sm-redis:6379','MEMORY_CACHE_ENABLED':'true','BATCH_UPDATE_ENABLED':'false','ERROR_LOG_ENABLED':'true','GIN_MODE':'release','NODE_NAME':'isolated-single-vs-multi','GLOBAL_API_RATE_LIMIT_ENABLE':'false','GLOBAL_WEB_RATE_LIMIT_ENABLE':'false','CRITICAL_RATE_LIMIT_ENABLE':'false','STREAMING_TIMEOUT':'10','RELAY_TIMEOUT':'15','TZ':'Asia/Shanghai'}
    env_args = [part for k,v in env.items() for part in ('-e',k+'='+v)]
    subprocess.run(common + ['--name','new-api-sm-app','--ip','172.19.0.3','--memory','512m','--cpus','0.75','--pids-limit','256','-v',str(ROOT/'data')+':/data'] + env_args + [originals[0]['Image']],check=True)
    subprocess.run(common + ['--name','new-api-sm-nginx','--ip','172.19.0.4','--memory','32m','--cpus','0.1','--pids-limit','64','-v',str(ROOT/'nginx.conf')+':/etc/nginx/nginx.conf:ro',originals[2]['Image']],check=True)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    ready=False
    for _ in range(30):
        try:
            with opener.open('http://172.19.0.4/api/status',timeout=2) as response:
                ready=json.load(response).get('success') is True
            if ready: break
        except Exception:
            pass
        time.sleep(1)
    if not ready: raise RuntimeError('fixture did not become ready')
    subprocess.run(['systemd-run','--unit=new-api-sm-mock-20260905','--property=MemoryMax=160M','--property=CPUQuota=40%','--property=TasksMax=160','--working-directory='+str(ROOT),'/usr/bin/python3','benchmark.py','serve','--host','172.19.0.1','--port','18082'],check=True)
    containers=[]
    for c in json.loads(subprocess.check_output(['docker','inspect',*names,'new-api-sm-app','new-api-sm-redis','new-api-sm-nginx'])):
        containers.append({'name':c['Name'].lstrip('/'),'image_id':c['Image'],'memory_bytes':c['HostConfig']['Memory'],'nano_cpus':c['HostConfig']['NanoCpus'],'running':c['State']['Running'],'oom_killed':c['State']['OOMKilled'],'restart_count':c['RestartCount'],'health':c['State'].get('Health',{}).get('Status')})
    manifest={'recorded_at':time.time(),'cpu_count':os.cpu_count(),'containers':containers,'test_env':env,'scope':'single vs multi simulated upstream, same image, no original database changes, not historical production or Agent results'}
    (ROOT/'results/environment.json').write_text(json.dumps(manifest,indent=2))
    print(json.dumps({'ready':ready,'public_test_port':False,'containers':len(containers)}))


if __name__ == '__main__':
    main()
