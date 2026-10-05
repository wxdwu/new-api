"""Manage only the disposable benchmark instance on its private bridge address."""
import argparse
import http.cookiejar
import json
import os
from pathlib import Path
import secrets
import sys
import urllib.request

BASE = 'http://172.19.0.4'
ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['init', 'set', 'state'])
    parser.add_argument('--mock-host')
    parser.add_argument('--config', default='{}')
    args = parser.parse_args()
    os.umask(0o077)
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(jar))
    uid = None

    def api(method, path, payload=None):
        headers = {'Content-Type': 'application/json'}
        if uid is not None:
            headers['New-Api-User'] = str(uid)
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
        with opener.open(request, timeout=15) as response:
            result = json.load(response)
        if result.get('success') is not True:
            raise RuntimeError(f'{method} {path} failed: {result.get("message", "no success flag")}')
        return result.get('data')

    def items(data):
        return data if isinstance(data, list) else data.get('items', [])

    private = ROOT / 'test-admin.private.json'
    if args.action == 'init':
        if private.exists():
            raise RuntimeError('test instance was already initialized; refusing to overwrite')
        setup = api('GET', '/api/setup')
        if setup.get('status') or setup.get('root_init'):
            raise RuntimeError('refusing to initialize an existing database')
        credential = {'username': 'bench-admin', 'password': secrets.token_urlsafe(12)}
        api('POST', '/api/setup', {**credential, 'confirmPassword': credential['password'],
                                  'SelfUseModeEnabled': False, 'DemoSiteEnabled': False})
        private.write_text(json.dumps(credential))
    credential = json.loads(private.read_text())
    login = api('POST', '/api/user/login', credential)
    uid = login['id']

    if args.action == 'init':
        if not args.mock_host:
            raise RuntimeError('--mock-host required')
        for key, value in {'RetryTimes': '0', 'AutomaticDisableChannelEnabled': 'false',
                           'AutomaticEnableChannelEnabled': 'false', 'ModelRequestRateLimitEnabled': 'false',
                           'performance_setting.monitor_enabled': 'false', 'LogConsumeEnabled': 'true'}.items():
            api('PUT', '/api/option/', {'key': key, 'value': value})
        api('POST', '/api/token/', {'name': 'isolated-benchmark', 'expired_time': -1,
                                   'unlimited_quota': True, 'group': 'default', 'cross_group_retry': False})
        tokens = items(api('GET', '/api/token/?p=1&page_size=10'))
        if len(tokens) != 1:
            raise RuntimeError('expected exactly one isolated token')
        key = api('POST', f'/api/token/{tokens[0]["id"]}/key', {})['key']
        (ROOT / 'test-token.private').write_text(key)
        for name in ('a', 'b', 'c'):
            api('POST', '/api/channel/', {'mode': 'single', 'channel': {
                'type': 1, 'name': f'benchmark-{name}', 'key': f'mock-only-{name}',
                'models': 'gpt-4o-mini', 'group': 'default', 'status': 1,
                'weight': 50, 'priority': 10, 'auto_ban': 0,
                'base_url': f'http://{args.mock_host}:18082/{name}'}})
        print('isolated benchmark admin, token and three mock channels initialized')

    channels = items(api('GET', '/api/channel/?p=1&page_size=10'))
    if len(channels) != 3 or {c['name'] for c in channels} != {'benchmark-a', 'benchmark-b', 'benchmark-c'}:
        raise RuntimeError('refusing to operate: channel set does not match isolated fixture')
    if args.action == 'set':
        config = json.loads(args.config)
        for key, value in config.get('options', {}).items():
            api('PUT', '/api/option/', {'key': key, 'value': str(value)})
        for channel in channels:
            change = config.get('channels', {}).get(channel['name'][-1])
            if change:
                allowed = {'weight', 'priority', 'auto_ban', 'status'}
                if set(change) - allowed:
                    raise RuntimeError('unsupported channel fixture change')
                patch = {k: v for k, v in change.items() if k != 'status'}
                if patch:
                    api('PUT', '/api/channel/', {'id': channel['id'], **patch})
                if 'status' in change:
                    api('POST', f'/api/channel/{channel["id"]}/status', {'status': change['status']})
        channels = items(api('GET', '/api/channel/?p=1&page_size=10'))
    fields = ('id', 'name', 'status', 'weight', 'priority', 'auto_ban')
    safe_options = {'RetryTimes', 'AutomaticDisableChannelEnabled', 'AutomaticEnableChannelEnabled',
                    'ModelRequestRateLimitEnabled', 'ModelRequestRateLimitCount',
                    'ModelRequestRateLimitDurationMinutes', 'ModelRequestRateLimitSuccessCount'}
    options = api('GET', '/api/option/')
    print(json.dumps({'channels': [{k: c.get(k) for k in fields} for c in channels],
                      'options': {x['key']: x['value'] for x in options if x['key'] in safe_options}}))


if __name__ == '__main__':
    main()
