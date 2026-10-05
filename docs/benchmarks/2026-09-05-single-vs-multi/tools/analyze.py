"""Recompute single-vs-multi outcomes and verify actual routing from saved attempts."""
import collections
import csv
import json
import math
from pathlib import Path
import sys


def pct(values, p):
    data = sorted(values)
    return data[max(0, math.ceil(p * len(data))-1)] if data else None


def main():
    root = Path(sys.argv[1])
    index = json.loads((root/'experiment-index.json').read_text())
    if len(index['runs']) != 12 or 'finished_at' not in index:
        raise RuntimeError('experiment is incomplete')
    unique_runs = set()
    pooled = collections.defaultdict(list)
    rows = []
    original_restarts = {c['name']: c['restart_count'] for c in index['initial_state']['containers']}
    for entry in index['runs']:
        rid = entry['run_id']
        scenario, arm = entry['scenario'], entry['arm']
        if (scenario,arm,entry['repeat']) in unique_runs:
            raise RuntimeError('duplicate experiment arm')
        unique_runs.add((scenario,arm,entry['repeat']))
        client = json.loads((root/(rid+'.client.json')).read_text())
        upstream = json.loads((root/(rid+'.upstream.json')).read_text())
        settings = entry['effective_config']
        if int(settings['options']['RetryTimes']) != (0 if arm == 'single' else 1):
            raise RuntimeError(f'{rid}: retry configuration mismatch')
        by_channel = {c['name'][-1]: c for c in settings['channels']}
        if set(by_channel) != {'a','b','c'}:
            raise RuntimeError(f'{rid}: fixture channel set mismatch')
        for name, weight, priority, capacity in [('a',25,20,8),('b',75,20,24),('c',100,10,32)]:
            expected_status = 2 if arm == 'single' and name != 'a' else 1
            channel = by_channel[name]
            if (channel['weight'],channel['priority'],channel['status'],channel['auto_ban']) != (weight,priority,expected_status,0):
                raise RuntimeError(f'{rid}: effective routing settings mismatch')
            expected = {'capacity':capacity,'fault_period_s':10 if scenario=='burst_fault' and name=='a' else 0,
                        'fault_window_s':2 if scenario=='burst_fault' and name=='a' else 0}
            metric = upstream['channels'][name]
            if metric['effective_config'] != expected or metric['inflight'] or metric['max_inflight'] > capacity:
                raise RuntimeError(f'{rid}: mock configuration/capacity/drain mismatch')
            if metric['attempts'] != len(metric['rows']) or metric['attempts'] != metric['success']+metric['rejected']+metric['fault']:
                raise RuntimeError(f'{rid}: upstream counts mismatch or disconnect')
        requests = client['rows']
        ids = {r['benchmark_id'] for r in requests}
        if len(requests) != 600 or len(ids) != 600 or client['rps'] != 20 or client['duration_s'] != 30:
            raise RuntimeError(f'{rid}: incorrect load or duplicate/missing requests')
        if client['summary']['actual_started_within_send_window'] != 600 or client['summary']['last_actual_start_offset_s'] >= 30:
            raise RuntimeError(f'{rid}: arrival window missed')
        attempts = collections.defaultdict(list)
        for name, metric in upstream['channels'].items():
            for a in metric['rows']:
                if a['benchmark_id'] not in ids:
                    raise RuntimeError(f'{rid}: unassociated upstream attempt')
                attempts[a['benchmark_id']].append(a)
                if a['status'] == 503 and (scenario != 'burst_fault' or name != 'a'):
                    raise RuntimeError(f'{rid}: unexpected fault source')
                if a['status'] == 429 and a['inflight'] < metric['effective_config']['capacity']:
                    raise RuntimeError(f'{rid}: 429 without exhausted mock capacity')
        if set(attempts) != ids:
            raise RuntimeError(f'{rid}: some requests did not reach mock; inspect gateway failure separately')
        recovered = collections.Counter()
        first_counts = collections.Counter()
        completion_mismatches = 0
        for r in requests:
            seq = sorted(attempts[r['benchmark_id']], key=lambda a:a['start'])
            first_counts[seq[0]['channel']] += 1
            if arm == 'single':
                if len(seq) != 1 or seq[0]['channel'] != 'a':
                    raise RuntimeError(f'{rid}: single-channel fixture routed elsewhere')
            else:
                if seq[0]['channel'] not in ('a','b') or len(seq) > 2:
                    raise RuntimeError(f'{rid}: primary pool or retry bound violated')
                if seq[0]['status'] == 200:
                    if len(seq) != 1:
                        raise RuntimeError(f'{rid}: retried successful response')
                elif seq[0]['status'] in (429,503):
                    if len(seq) != 2 or seq[1]['channel'] != 'c' or seq[1]['start'] < seq[0]['end']:
                        raise RuntimeError(f'{rid}: priority fallback sequence incorrect')
                    if seq[1]['status'] == 200 and r['outcome'] == 'success':
                        recovered[seq[0]['status']] += 1
                else:
                    raise RuntimeError(f'{rid}: unexpected mock status')
            if seq[-1]['status'] == 200 and r['outcome'] != 'success':
                completion_mismatches += 1
        for state in (entry['state_before'],entry['state_after']):
            for c in state['containers']:
                if not c['running'] or c['oom_killed'] or c['health']=='unhealthy' or c['restart_count']!=original_restarts[c['name']]:
                    raise RuntimeError(f'{rid}: container state changed')
        success = [r for r in requests if r['outcome']=='success']
        if len(success) != client['summary']['success']:
            raise RuntimeError(f'{rid}: summary differs from raw outcomes')
        counts = collections.Counter(r['status_code'] for r in requests)
        rows.append({'run_id':rid,'scenario':scenario,'arm':arm,'requests':600,'success':len(success),
                     'failure':600-len(success),'failure_rate_pct':100*(600-len(success))/600,
                     'p95_success_s':pct([r['latency_s'] for r in success],.95),
                     'p99_success_s':pct([r['latency_s'] for r in success],.99),
                     'p95_first_output_s':pct([r['first_output_latency_s'] for r in success],.95),
                     'http_429':counts[429],'http_503':counts[503],
                     'upstream_attempts':sum(len(v) for v in attempts.values()),
                     'a_first':first_counts['a'],'b_first':first_counts['b'],
                     'c_attempts':upstream['channels']['c']['attempts'],
                     'recovered_429':recovered[429],'recovered_503':recovered[503],
                     'post_upstream_completion_failures':completion_mismatches,
                     'max_scheduling_delay_s':max(r['scheduling_delay_s'] for r in requests)})
        pooled[(scenario,arm)].extend(requests)
    expected_runs = {(s,a,r) for s in ('burst','burst_fault') for a in ('single','multi') for r in (1,2,3)}
    if unique_runs != expected_runs:
        raise RuntimeError('missing or unexpected runs')
    aggregate = []
    for (scenario,arm), requests in sorted(pooled.items()):
        success = [r for r in requests if r['outcome']=='success']
        runs = [r for r in rows if r['scenario']==scenario and r['arm']==arm]
        aggregate.append({'scenario':scenario,'arm':arm,'requests':len(requests),'success':len(success),
                          'failure':len(requests)-len(success),'failure_rate_pct':100*(len(requests)-len(success))/len(requests),
                          'p95_success_s':pct([r['latency_s'] for r in success],.95),
                          'p99_success_s':pct([r['latency_s'] for r in success],.99),
                          'p95_first_output_s':pct([r['first_output_latency_s'] for r in success],.95),
                          'upstream_attempts':sum(r['upstream_attempts'] for r in runs),
                          'attempt_amplification':sum(r['upstream_attempts'] for r in runs)/len(requests),
                          'a_first_share_pct':100*sum(r['a_first'] for r in runs)/len(requests),
                          'recovered_429':sum(r['recovered_429'] for r in runs),
                          'recovered_503':sum(r['recovered_503'] for r in runs),
                          'per_run_failure_rate_pct':[r['failure_rate_pct'] for r in runs]})
    report = {'validation':'passed: all 7200 requests, effective single/multi settings, exact primary/backup sequences, counts, arrival windows and container state checked',
              'scope':index['scope'],'aggregate':aggregate,'per_run':rows,
              'note':'single A capacity 8 vs primary A+B capacity 32 plus backup C capacity 32; combined capacity and routing/retry effect, not algorithm-only or historical production improvement'}
    (root/'summary.json').write_text(json.dumps(report,indent=2))
    with (root/'per-run.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    print(json.dumps({'validation':report['validation'],'aggregate':aggregate},indent=2))


if __name__ == '__main__':
    main()
