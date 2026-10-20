# -*- coding: utf-8 -*-
import json
from types import SimpleNamespace

import cli
import config
import core


def test_targets_from_args(temp_config):
    args = SimpleNamespace(
        target=['10.0.0.1', 'bad', '10.0.0.2:8080'], target_file='')
    targets = cli._targets(args)
    assert [t.line for t in targets] == ['10.0.0.1', '10.0.0.2:8080']


def test_cli_scan(temp_config, monkeypatch, capsys):
    monkeypatch.setattr(core, 'scan_hosts',
                        lambda *a, **k: ['10.0.0.1', '10.0.0.2'])
    rc = cli.main(['scan', '--my-ip', '10.0.0.5', '--save'])
    out = capsys.readouterr().out
    assert rc == 0
    assert '10.0.0.1' in out
    assert (temp_config / 'ip.txt').read_text(encoding='utf-8').splitlines() == \
        ['10.0.0.1', '10.0.0.2']
    state = config.load_state()
    assert state['alive'] == ['10.0.0.1', '10.0.0.2']


def test_cli_scan_json(temp_config, monkeypatch, capsys):
    monkeypatch.setattr(core, 'scan_hosts', lambda *a, **k: ['10.0.0.1'])
    rc = cli.main(['scan', '--my-ip', '10.0.0.5', '--json'])
    assert rc == 0
    out = capsys.readouterr().out
    assert json.loads(out) == {'alive': ['10.0.0.1']}


def test_cli_write(temp_config, monkeypatch, capsys):
    monkeypatch.setattr(core, 'write_busima_ex', lambda *a, **k: (True, 'ok'))
    rc = cli.main(['write', '--target', '10.0.0.1',
                   '--url', 'http://127.0.0.1/shell.php'])
    out = capsys.readouterr().out
    assert rc == 0
    assert 'OK' in out
    state = config.load_state()
    assert state['written'] == ['10.0.0.1']


def test_cli_write_headers(temp_config, monkeypatch, capsys):
    monkeypatch.setattr(
        core, 'write_busima_ex',
        lambda session, target, options:
        (True, 'headers=%s' % ','.join(sorted(options.get('headers', {})))))
    rc = cli.main(['write', '--target', '10.0.0.1',
                   '--url', 'http://127.0.0.1/shell.php',
                   '--header', 'X-Test: 1'])
    out = capsys.readouterr().out
    assert rc == 0
    assert 'X-Test' in out


def test_cli_fetch(temp_config, monkeypatch, capsys):
    monkeypatch.setattr(core, 'fetch_flag_detail',
                        lambda *a, **k: ('flag{cli}', 'ok', '/flag'))
    rc = cli.main(['fetch', '--target', '10.0.0.1',
                   '--url', 'http://127.0.0.1/shell.php'])
    out = capsys.readouterr().out
    assert rc == 0
    assert 'flag{cli}' in out
    state = config.load_state()
    assert state['last_flag']['10.0.0.1'] == 'flag{cli}'
    assert state['flag_path']['10.0.0.1'] == '/flag'


def test_cli_submit(temp_config, monkeypatch, capsys):
    monkeypatch.setattr(core, 'fetch_flag_detail',
                        lambda *a, **k: ('flag{cli}', 'ok', '/flag'))

    class Resp(object):
        text = '{"code":0,"msg":"ok"}'
        status_code = 200

    monkeypatch.setattr(core, 'submit_flag_retry', lambda *a, **k: Resp())
    raw = ('POST /s HTTP/1.1\r\nHost: 10.0.0.1\r\n'
           'Content-Type: application/x-www-form-urlencoded\r\n\r\n')
    rc = cli.main(['submit', '--target', '10.0.0.1',
                   '--url', 'http://127.0.0.1/shell.php',
                   '--raw', raw, '--param', 'flag'])
    out = capsys.readouterr().out
    assert rc == 0
    assert '成功' in out
    state = config.load_state()
    assert state['submitted']['10.0.0.1'] == 'flag{cli}'


def test_cli_submit_requires_raw(temp_config):
    rc = cli.main(['submit', '--target', '10.0.0.1'])
    assert rc == 2


def test_cli_submit_dry_run(temp_config, capsys):
    raw = ('POST /s HTTP/1.1\r\nHost: 10.0.0.1\r\n'
           'Content-Type: application/x-www-form-urlencoded\r\n\r\n'
           'foo=1&flag=old')
    rc = cli.main(['submit', '--raw', raw, '--param', 'flag', '--dry-run'])
    out = capsys.readouterr().out
    assert rc == 0
    assert 'METHOD: POST' in out
    assert 'flag=flag%7BPREVIEW%7D' in out
    assert not (temp_config / 'state.json').exists()


def test_cli_submit_dedupe(temp_config, monkeypatch, capsys):
    monkeypatch.setattr(
        core, 'fetch_flag_detail',
        lambda *a, **k: ('flag{same}', 'ok', ''))

    class Resp(object):
        text = '{"code":0}'
        status_code = 200

    monkeypatch.setattr(core, 'submit_flag_retry', lambda *a, **k: Resp())
    raw = ('POST /s HTTP/1.1\r\nHost: 10.0.0.1\r\n'
           'Content-Type: application/x-www-form-urlencoded\r\n\r\n')
    rc = cli.main(['submit', '--target', '10.0.0.1', '--target', '10.0.0.2',
                   '--url', 'http://127.0.0.1/shell.php',
                   '--raw', raw, '--param', 'flag', '--workers', '1',
                   '--dedupe'])
    out = capsys.readouterr().out
    assert rc == 0
    assert out.count('成功') == 1
    assert '跳过（重复 flag）' in out
    assert len(config.load_state()['submitted']) == 1


def test_cli_command(temp_config, monkeypatch, capsys):
    monkeypatch.setattr(core, 'exec_shell',
                        lambda *a, **k: ('uid=0(root)', None))
    rc = cli.main(['command', '--target', '10.0.0.1', '--cmd', 'id'])
    out = capsys.readouterr().out
    assert rc == 0
    assert 'uid=0(root)' in out


def test_cli_health(temp_config, monkeypatch, capsys):
    monkeypatch.setattr(core, 'check_shell', lambda *a, **k: (True, 'ok'))
    rc = cli.main(['health', '--target', '10.0.0.1'])
    out = capsys.readouterr().out
    assert rc == 0
    assert 'ALIVE' in out
    assert config.load_state()['alive'] == ['10.0.0.1']


def test_cli_check(temp_config, monkeypatch, capsys):
    monkeypatch.setattr(
        core, 'defense_check',
        lambda *a, **k: {'error': '', 'sections': {}, 'raw': '',
                         'findings': [('正常', '未发现明显风险', '')]})
    rc = cli.main(['check', '--target', '10.0.0.1'])
    out = capsys.readouterr().out
    assert rc == 0
    assert '未发现明显风险' in out


def test_cli_check_severe(temp_config, monkeypatch, capsys):
    monkeypatch.setattr(
        core, 'defense_check',
        lambda *a, **k: {'error': '', 'sections': {}, 'raw': '',
                         'findings': [('严重', '可能的 webshell', '/x.php')]})
    rc = cli.main(['check', '--target', '10.0.0.1'])
    out = capsys.readouterr().out
    assert rc == 1
    assert '[严重]' in out


def test_cli_probe(temp_config, monkeypatch, capsys):
    monkeypatch.setattr(
        core, 'probe_target',
        lambda target, timeout=None:
        (target.port == 8080, 'TCP %s:%s' % (target.ip, target.port)))
    rc = cli.main(['probe', '--target', '10.0.0.1',
                   '--target', '10.0.0.2:8080'])
    out = capsys.readouterr().out
    assert rc == 0
    assert '10.0.0.2:8080' in out
    assert 'ALIVE' in out
    assert config.load_state()['alive'] == ['10.0.0.2:8080']
