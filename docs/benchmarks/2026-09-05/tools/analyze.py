"""Independently validate and summarize saved client/upstream samples."""
import collections
import csv
import json
import math
from pathlib import Path
import statistics
import sys


def percentile(values, p):
    values = sorted(values)
    return values[max(0, math.ceil(len(values) * p) - 1)] if values else None


def wilson(fail, n):
    z = 1.96
    center = (fail / n + z * z / (2 * n)) / (1 + z * z / n)
    radius = z * math.sqrt((fail / n) * (1 - fail / n) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [100 * (center - radius), 100 * (center + radius)]


def main():
    root = Path(sys.argv[1])
    index = json.loads((root / 'experiment-index.json').read_text())
    if len(index['runs']) != 12 or 'finished_at' not in index:
        raise RuntimeError('formal experiment set incomplete')
    pooled = collections.defaultdict(list)
    attempts = collections.Counter()
    rows = []
    for entry in index['runs']:
        rid = entry['run_id']
        client = json.loads((root / (rid + '.client.json')).read_text())
        upstream = json.loads((root / (rid + '.upstream.json')).read_text())
        config = entry['effective_config']
        channels = {c['name'][-1]: c for c in config['channels']}
        retry = 0 if entry['scenario'] == 'weighted' or entry['arm'] == 'baseline' else 1
        if int(config['options']['RetryTimes']) != retry:
            raise RuntimeError(f'{rid}: effective retry configuration mismatch')
        if entry['scenario'] == 'weighted':
            weights = (90, 10) if entry['arm'] == 'baseline' else (25, 75)
            expected_priorities = (10, 10)
            expected_mock = {'a': {'capacity': 8, 'fault_period_s': 0, 'fault_window_s': 0},
                             'b': {'capacity': 24, 'fault_period_s': 0, 'fault_window_s': 0}}
        else:
            weights = (50, 50)
            expected_priorities = (20, 10)
            expected_mock = {'a': {'capacity': 32, 'fault_period_s': 10, 'fault_window_s': 2},
                             'b': {'capacity': 32, 'fault_period_s': 0, 'fault_window_s': 0}}
        for name, weight, priority in zip(('a', 'b'), weights, expected_priorities):
            c = channels[name]
            if (c['weight'], c['priority'], c['status'], c['auto_ban']) != (weight, priority, 1, 0):
                raise RuntimeError(f'{rid}: effective channel configuration mismatch')
            if upstream['channels'][name]['effective_config'] != expected_mock[name]:
                raise RuntimeError(f'{rid}: mock configuration mismatch')
        requests = client['rows']
        ids = {r['benchmark_id'] for r in requests}
        expected = round(client['rps'] * client['duration_s'])
        if len(requests) != expected or len(ids) != expected:
            raise RuntimeError(f'{rid}: missing/duplicate client requests')
        by_id = collections.defaultdict(list)
        for channel, data in upstream['channels'].items():
            if len(data['rows']) != data['attempts'] or data['inflight']:
                raise RuntimeError(f'{rid}: upstream rows/count/drain mismatch')
            if data['max_inflight'] > data['effective_config']['capacity']:
                raise RuntimeError(f'{rid}: upstream capacity invariant violated')
            for row in data['rows']:
                if row['benchmark_id'] not in ids:
                    raise RuntimeError(f'{rid}: unmatched upstream ID')
                by_id[row['benchmark_id']].append(row)
        if set(by_id) != ids:
            raise RuntimeError(f'{rid}: some requests did not reach mock upstream')
        recovered = 0
        for request in requests:
            seq = sorted(by_id[request['benchmark_id']], key=lambda attempt: attempt['start'])
            observed = [(a['channel'], a['status']) for a in seq]
            if entry['scenario'] == 'weighted':
                if len(seq) != 1 or seq[0]['status'] not in (200, 429):
                    raise RuntimeError(f'{rid}: weighted request attempt contract failed')
            elif entry['arm'] == 'baseline':
                if observed not in ([('a', 200)], [('a', 503)]):
                    raise RuntimeError(f'{rid}: priority baseline contract failed')
            elif observed == [('a', 503), ('b', 200)]:
                if seq[1]['start'] < seq[0]['end']:
                    raise RuntimeError(f'{rid}: fallback began before first attempt ended')
                recovered += 1
            elif observed != [('a', 200)]:
                raise RuntimeError(f'{rid}: retry fallback contract failed')
            expected_success = seq[-1]['status'] == 200
            if (request['outcome'] == 'success') != expected_success:
                raise RuntimeError(f'{rid}: client/upstream completion mismatch')
        if client['summary']['actual_started_within_send_window'] != expected:
            raise RuntimeError(f'{rid}: some requests started outside arrival window')
        if client['summary']['last_actual_start_offset_s'] >= client['duration_s']:
            raise RuntimeError(f'{rid}: last start outside arrival window')
        if max(r['scheduling_delay_s'] for r in requests) > 0.1:
            raise RuntimeError(f'{rid}: load driver scheduling delayed beyond 100ms')
        total_attempts = sum(len(v) for v in by_id.values())
        successes = sum(r['outcome'] == 'success' for r in requests)
        if successes != client['summary']['success']:
            raise RuntimeError(f'{rid}: client summary mismatch')
        key = (entry['scenario'], entry['arm'])
        pooled[key].extend(requests)
        attempts[key] += total_attempts
        counts = collections.Counter(r['status_code'] for r in requests)
        successful = [r for r in requests if r['outcome'] == 'success']
        rows.append({'run_id': rid, 'scenario': key[0], 'arm': key[1], 'requests': expected,
                     'success': successes, 'failure': expected - successes,
                     'failure_rate_pct': 100 * (expected - successes) / expected,
                     'p95_success_s': percentile([r['latency_s'] for r in successful], 0.95),
                     'p95_first_output_s': percentile([r['first_output_latency_s'] for r in successful], 0.95),
                     'max_schedule_delay_s': max(r['scheduling_delay_s'] for r in requests),
                     'http_429': counts[429], 'http_503': counts[503], 'upstream_attempts': total_attempts,
                     'recovered_via_b': recovered, 'a_share_pct': 100 * upstream['channels']['a']['attempts'] / total_attempts,
                     'a_attempts': upstream['channels']['a']['attempts'], 'b_attempts': upstream['channels']['b']['attempts']})
    aggregate = []
    for (scenario, arm), requests in sorted(pooled.items()):
        success = [r for r in requests if r['outcome'] == 'success']
        failed = len(requests) - len(success)
        aggregate.append({'scenario': scenario, 'arm': arm, 'requests': len(requests),
                          'success': len(success), 'failure': failed, 'failure_rate_pct': 100 * failed / len(requests),
                          'binomial_wilson_95_pct_descriptive': wilson(failed, len(requests)),
                          'p95_success_s': percentile([r['latency_s'] for r in success], 0.95),
                          'p99_success_s': percentile([r['latency_s'] for r in success], 0.99),
                          'p95_first_output_s': percentile([r['first_output_latency_s'] for r in success], 0.95),
                          'upstream_attempts': attempts[(scenario, arm)],
                          'attempt_amplification': attempts[(scenario, arm)] / len(requests),
                          'per_run_failure_rate_pct': [r['failure_rate_pct'] for r in rows if r['scenario'] == scenario and r['arm'] == arm]})
    summary = {'validation': 'passed: 12 complete runs; effective settings, mock conditions, exact attempt sequences, client completion, arrival windows, counts and capacity checked',
               'scope': index['scope'], 'per_run': rows, 'aggregate': aggregate,
               'statistics_note': 'fault periods create correlated outcomes; pooled binomial intervals are descriptive only, retain per-run variation'}
    (root / 'summary.json').write_text(json.dumps(summary, indent=2))
    with (root / 'per-run.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({'validation': summary['validation'], 'aggregate': aggregate}, indent=2))


if __name__ == '__main__':
    main()
