"""Single enabled channel versus weighted primary pool plus priority backup."""
import collections
import json
from pathlib import Path
import subprocess
import sys
import time
import os

import benchmark

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / 'results'
URL = 'http://172.19.0.4/v1/responses'
MOCK = 'http://172.19.0.1:18082'
TOKEN = str(ROOT / 'test-token.private')
NAMES = ['new-api-cloud-new-api-1', 'new-api-cloud-nginx-1', 'new-api-cloud-mysql-1',
         'new-api-cloud-redis-1', 'new-api-sm-app', 'new-api-sm-redis', 'new-api-sm-nginx']


def snapshot():
    rows = []
    for c in json.loads(subprocess.check_output(['docker', 'inspect', *NAMES])):
        s = c['State']
        row = {'name': c['Name'].lstrip('/'), 'running': s['Running'], 'oom_killed': s['OOMKilled'],
               'restart_count': c['RestartCount'], 'health': s.get('Health', {}).get('Status')}
        if not row['running'] or row['oom_killed'] or row['health'] == 'unhealthy':
            raise RuntimeError('container safety guard failed')
        rows.append(row)
    available = next(int(l.split()[1]) for l in open('/proc/meminfo') if l.startswith('MemAvailable:'))
    if available < 750 * 1024:
        raise RuntimeError('host available memory below 750 MiB; stopping before next run')
    return {'recorded_at': time.time(), 'containers': rows, 'load': os.getloadavg(), 'memory_available_kib': available}


def configuration(arm):
    return {'options': {'RetryTimes': '0' if arm == 'single' else '1'}, 'channels': {
        'a': {'weight': 25, 'priority': 20, 'status': 1},
        'b': {'weight': 75, 'priority': 20, 'status': 2 if arm == 'single' else 1},
        'c': {'weight': 100, 'priority': 10, 'status': 2 if arm == 'single' else 1}}}


def configure(arm):
    output = subprocess.check_output([sys.executable, str(ROOT/'admin.py'), 'set', '--config', json.dumps(configuration(arm))], text=True)
    actual = json.loads(output.splitlines()[-1])
    intended = configuration(arm)
    if actual['options']['RetryTimes'] != intended['options']['RetryTimes']:
        raise RuntimeError('retry setting did not take effect')
    for c in actual['channels']:
        expected = intended['channels'][c['name'][-1]]
        if any(c[k] != v for k, v in expected.items()) or c['auto_ban'] != 0:
            raise RuntimeError('channel setting did not take effect')
    return actual


def control(scenario):
    return {'channels': {
        'a': {'capacity': 8, 'fault_period_s': 10 if scenario == 'burst_fault' else 0,
              'fault_window_s': 2 if scenario == 'burst_fault' else 0},
        'b': {'capacity': 24, 'fault_period_s': 0, 'fault_window_s': 0},
        'c': {'capacity': 32, 'fault_period_s': 0, 'fault_window_s': 0}},
        'duration_s': 1, 'first_token_s': 0.2, 'fault_period_s': 0, 'fault_window_s': 0, 'reset': True}


def load(run_id, rps, duration, stream=True, save=True):
    return benchmark.run_load(url=URL, token_file=TOKEN, run_id=run_id, rps=rps, duration=duration,
                              output=str(RESULTS/(run_id+'.client.json')) if save else None,
                              model='gpt-4o-mini', stream=stream)


def metrics_after_drain():
    deadline = time.monotonic() + 2
    while True:
        data = benchmark.get_json(MOCK+'/metrics')
        if not any(c['inflight'] for c in data['channels'].values()):
            return data
        if time.monotonic() >= deadline:
            raise RuntimeError('mock did not drain')
        time.sleep(0.02)


def preflight():
    configure('single')
    benchmark.post_json(MOCK+'/control', control('burst'))
    for stream in (False, True):
        r = load('smoke-single-'+str(stream), 2, 1, stream)
        if r['summary']['success'] != 2:
            raise RuntimeError('single channel JSON/SSE smoke failed')
    data = metrics_after_drain()
    if data['channels']['a']['attempts'] != 4 or any(data['channels'][c]['attempts'] for c in ('b','c')):
        raise RuntimeError('disabled channels received traffic')
    (RESULTS/'smoke-single.upstream.json').write_text(json.dumps(data, indent=2))
    configure('multi')
    fault = control('burst')
    for c in ('a','b'):
        fault['channels'][c].update(fault_period_s=60, fault_window_s=60)
    benchmark.post_json(MOCK+'/control', fault)
    r = load('smoke-backup', 2, 2)
    data = metrics_after_drain()
    if r['summary']['success'] != 4 or data['channels']['c']['success'] != 4:
        raise RuntimeError('priority backup smoke failed')
    (RESULTS/'smoke-backup.upstream.json').write_text(json.dumps(data, indent=2))
    print(json.dumps({'event': 'preflight_passed', 'single_json_sse': 4, 'backup_sse': 4}), flush=True)


def main():
    index_file = RESULTS/'experiment-index.json'
    if index_file.exists():
        raise RuntimeError('refusing to overwrite previous experiment results')
    preflight()
    index = {'started_at': time.time(), 'scope': 'isolated single-channel vs three-channel HTTP Responses SSE, same image, synthetic capacity and faults; not historical production or Agent results',
             'duration_s': 30, 'rps': 20, 'repeats_per_arm': 3, 'initial_state': snapshot(), 'runs': []}
    index_file.write_text(json.dumps(index, indent=2))
    for scenario in ('burst', 'burst_fault'):
        for repeat in range(1, 4):
            for arm in (('single','multi') if repeat % 2 else ('multi','single')):
                rid = f'{scenario}-{repeat}-{arm}'
                before = snapshot()
                actual = configure(arm)
                benchmark.post_json(MOCK+'/control', control('burst'))
                warm = load(rid+'-warmup', 2, 1, save=False)
                if warm['summary']['success'] != 2:
                    raise RuntimeError('warmup failed; formal run not started')
                metrics_after_drain()
                intended = control(scenario)
                benchmark.post_json(MOCK+'/control', intended)
                print(json.dumps({'event': 'run_started', 'run_id': rid}), flush=True)
                client = load(rid, 20, 30)
                upstream = metrics_after_drain()
                (RESULTS/(rid+'.upstream.json')).write_text(json.dumps(upstream, indent=2))
                entry = {'run_id': rid, 'scenario': scenario, 'arm': arm, 'repeat': repeat,
                         'effective_config': actual, 'control': intended, 'client': client['summary'],
                         'state_before': before, 'state_after': snapshot()}
                index['runs'].append(entry)
                index_file.write_text(json.dumps(index, indent=2))
                counts = collections.Counter(r['status_code'] for r in client['rows'])
                print(json.dumps({'event': 'run_finished', 'run_id': rid, 'success': client['summary']['success'],
                                  'failed': 600-client['summary']['success'], 'http': counts,
                                  'p95_s': client['summary']['latency_p95_s'],
                                  'attempts': {c: d['attempts'] for c,d in upstream['channels'].items()}}), flush=True)
    index['finished_at'] = time.time()
    index['final_state'] = snapshot()
    index_file.write_text(json.dumps(index, indent=2))


if __name__ == '__main__':
    main()
