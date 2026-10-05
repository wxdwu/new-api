"""Run bounded paired experiments only against this disposable server fixture."""
import json
from pathlib import Path
import subprocess
import sys
import time

import benchmark

ROOT = Path(__file__).resolve().parent
MOCK = 'http://172.19.0.1:18081'
URL = 'http://172.19.0.4/v1/responses'
TOKEN = str(ROOT / 'test-token.private')
RESULTS = ROOT / 'results'


def state_snapshot():
    containers = ['new-api-cloud-new-api-1', 'new-api-cloud-nginx-1',
                  'new-api-cloud-mysql-1', 'new-api-cloud-redis-1',
                  'new-api-bench-app', 'new-api-bench-nginx', 'new-api-bench-redis']
    data = json.loads(subprocess.check_output(['docker', 'inspect', *containers]))
    safe = []
    for item in data:
        state = item['State']
        safe.append({'name': item['Name'].lstrip('/'), 'running': state['Running'],
                     'oom_killed': state['OOMKilled'], 'restart_count': item['RestartCount'],
                     'health': state.get('Health', {}).get('Status')})
        if not state['Running'] or state['OOMKilled'] or state.get('Health', {}).get('Status') == 'unhealthy':
            raise RuntimeError('container state guard failed')
    return safe


def configure(config):
    proc = subprocess.run([sys.executable, str(ROOT / 'admin.py'), 'set', '--config', json.dumps(config)],
                          check=True, capture_output=True, text=True)
    return json.loads(proc.stdout.splitlines()[-1])


def main():
    RESULTS.mkdir(exist_ok=True)
    output = RESULTS / 'experiment-index.json'
    if output.exists():
        raise RuntimeError('refusing to overwrite a completed or partial experiment index')
    states = state_snapshot()
    index = {'started_at': time.time(), 'initial_containers': states,
             'scope': 'isolated gateway HTTP Responses SSE with simulated upstream; not real Agent or production improvement',
             'duration_per_run_s': 30, 'repeats_per_arm': 3, 'runs': []}
    with (RESULTS / 'container-stats.jsonl').open('w') as stats_file:
        sampler = subprocess.Popen(['docker', 'stats', '--format', '{{json .}}'], stdout=stats_file, stderr=subprocess.DEVNULL)
        try:
            for scenario in ('weighted', 'retry'):
                for repeat in range(1, 4):
                    arms = ('baseline', 'optimized') if repeat % 2 else ('optimized', 'baseline')
                    for arm in arms:
                        run_id = f'{scenario}-{repeat}-{arm}'
                        state_snapshot()
                        if scenario == 'weighted':
                            weights = (90, 10) if arm == 'baseline' else (25, 75)
                            config = {'options': {'RetryTimes': '0'},
                                      'channels': {'a': {'weight': weights[0], 'priority': 10},
                                                   'b': {'weight': weights[1], 'priority': 10}}}
                            control = {'channels': {'a': {'capacity': 8, 'fault_period_s': 0, 'fault_window_s': 0},
                                                    'b': {'capacity': 24, 'fault_period_s': 0, 'fault_window_s': 0}},
                                       'duration_s': 1, 'first_token_s': 0.2, 'fault_period_s': 0,
                                       'fault_window_s': 0, 'reset': True}
                            rps = 20
                        else:
                            config = {'options': {'RetryTimes': '0' if arm == 'baseline' else '1'},
                                      'channels': {'a': {'weight': 50, 'priority': 20},
                                                   'b': {'weight': 50, 'priority': 10}}}
                            control = {'channels': {'a': {'capacity': 32, 'fault_period_s': 10, 'fault_window_s': 2},
                                                    'b': {'capacity': 32, 'fault_period_s': 0, 'fault_window_s': 0}},
                                       'duration_s': 1, 'first_token_s': 0.2, 'fault_period_s': 0,
                                       'fault_window_s': 0, 'reset': True}
                            rps = 10
                        effective = configure(config)
                        warm_control = json.loads(json.dumps(control))
                        for channel in warm_control['channels'].values():
                            channel['fault_period_s'] = 0
                            channel['fault_window_s'] = 0
                        benchmark.post_json(MOCK + '/control', warm_control)
                        warm = benchmark.run_load(url=URL, token_file=TOKEN, run_id=run_id + '-warmup',
                                                  rps=2, duration=1, output=None, model='gpt-4o-mini', stream=True)
                        if warm['summary']['success'] != warm['summary']['planned_requests']:
                            raise RuntimeError('warmup/protocol check failed; formal run not started')
                        benchmark.post_json(MOCK + '/control', control)
                        print(json.dumps({'event': 'run_started', 'run_id': run_id, 'rps': rps}), flush=True)
                        client = benchmark.run_load(url=URL, token_file=TOKEN, run_id=run_id, rps=rps,
                                                    duration=30, output=str(RESULTS / (run_id + '.client.json')),
                                                    model='gpt-4o-mini', stream=True)
                        upstream = benchmark.get_json(MOCK + '/metrics')
                        if any(c['inflight'] for c in upstream['channels'].values()):
                            raise RuntimeError('upstream did not drain before metrics capture')
                        (RESULTS / (run_id + '.upstream.json')).write_text(json.dumps(upstream, indent=2))
                        entry = {'run_id': run_id, 'scenario': scenario, 'arm': arm, 'repeat': repeat,
                                 'effective_config': effective, 'control': control, 'client': client['summary'],
                                 'upstream': {k: {f: v for f, v in c.items() if f != 'rows'} for k, c in upstream['channels'].items()},
                                 'containers_after': state_snapshot()}
                        index['runs'].append(entry)
                        output.write_text(json.dumps(index, indent=2))
                        print(json.dumps({'event': 'run_finished', 'run_id': run_id, 'client': client['summary'],
                                          'upstream_attempts': sum(c['attempts'] for c in upstream['channels'].values())}), flush=True)
            index['finished_at'] = time.time()
            index['final_containers'] = state_snapshot()
            output.write_text(json.dumps(index, indent=2))
        finally:
            sampler.terminate()
            sampler.wait(timeout=10)


if __name__ == '__main__':
    main()
