"""Remove only this experiment's temporary services after results are secured."""
import json
from pathlib import Path
import shutil
import subprocess
import time

ROOT=Path('/opt/new-api-single-multi-20260905')


def main():
    if Path(__file__).resolve().parent != ROOT:
        raise RuntimeError('cleanup is restricted to its exact server test directory')
    index=json.loads((ROOT/'results/experiment-index.json').read_text())
    if len(index['runs'])!=12 or 'finished_at' not in index:
        raise RuntimeError('formal experiment incomplete; preserve for inspection')
    subprocess.run(['systemctl','stop','new-api-sm-mock-20260905.service'],check=True)
    subprocess.run(['docker','rm','-f','new-api-sm-app','new-api-sm-nginx','new-api-sm-redis'],check=True)
    subprocess.run(['docker','network','rm','new-api-sm-20260905'],check=True)
    for name in ('test-admin.private.json','test-token.private'):
        (ROOT/name).unlink()
    shutil.rmtree(ROOT/'data')
    originals=[c for c in index['initial_state']['containers'] if c['name'].startswith('new-api-cloud-')]
    baseline={c['name']:c for c in originals}
    final=[]
    for c in json.loads(subprocess.check_output(['docker','inspect',*baseline])):
        s=c['State'];name=c['Name'].lstrip('/')
        row={'name':name,'running':s['Running'],'oom_killed':s['OOMKilled'],'restart_count':c['RestartCount'],'health':s.get('Health',{}).get('Status')}
        if not row['running'] or row['oom_killed'] or row['health']=='unhealthy' or row['restart_count']!=baseline[name]['restart_count']:
            raise RuntimeError('original service state changed')
        final.append(row)
    result={'recorded_at':time.time(),'temporary_containers_removed':True,'private_network_removed':True,'mock_stopped':True,'test_credentials_and_database_removed':True,'original_containers':final}
    (ROOT/'results/cleanup.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result))


if __name__=='__main__':
    main()
