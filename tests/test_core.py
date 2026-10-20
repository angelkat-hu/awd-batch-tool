# -*- coding: utf-8 -*-
import base64
import hashlib
import re
import socket

import pytest
import requests

import config
import core


class FakeResponse(object):
    def __init__(self, text='ok', status_code=200):
        self.text = text
        self.status_code = status_code
        self.headers = {}
        self.content = text.encode('utf-8')


class FakeSession(object):
    def __init__(self, response=None):
        self.calls = []
        self.response = response or FakeResponse()

    def _record(self, method, args, kwargs):
        self.calls.append((method, args, kwargs))
        return self.response

    def get(self, *args, **kwargs):
        return self._record('GET', args, kwargs)

    def post(self, *args, **kwargs):
        return self._record('POST', args, kwargs)

    def request(self, method, *args, **kwargs):
        return self._record(method, args, kwargs)


class ShellSession(FakeSession):
    """入口/落地 shell 都能返回 angelkat 的假会话"""

    def post(self, url, *args, **kwargs):
        self.calls.append(('POST', (url,), kwargs))
        if url.endswith('/upload/-.php'):
            return FakeResponse('angelkat')
        return FakeResponse('ok')


class NativeSession(FakeSession):
    """system 取不到、readfile 能取到的假会话"""

    def post(self, url, *args, **kwargs):
        self.calls.append(('POST', (url,), kwargs))
        data = kwargs.get('data') or {}
        php = data.get(config.木马密码, '')
        if 'readfile' in php:
            return FakeResponse('angelkatflag{native}angelkat')
        return FakeResponse('angelkat\nangelkat')


# ---------------------------------------------------------------- IP / 目标
@pytest.mark.parametrize('text,expected', [
    ('10.3.4.139', '10.3.4.'),
    ('10.3.4.', '10.3.4.'),
    ('10.3.', '10.3.'),
    (' 10.3.4.7 ', '10.3.4.'),
])
def test_parse_ip_field_ok(text, expected):
    assert core.parse_ip_field(text) == expected


@pytest.mark.parametrize('text', [
    '10.3.4.999', '10.3.4.0/24', '', 'abc', '1.2.3.4.5', '256.1.1.1',
    '10..3.4', '.10.3.4',
])
def test_parse_ip_field_bad(text):
    assert core.parse_ip_field(text) is None


def test_iter_scan_ip():
    ips = core.iter_scan_ip('10.3.4.', '10.3.4.139')
    assert len(ips) == 253
    assert '10.3.4.139' not in ips
    assert ips[0] == '10.3.4.1'
    assert ips[-1] == '10.3.4.254'

    ips16 = core.iter_scan_ip('10.3.', '10.3.4.139')
    assert len(ips16) == 64769
    assert '10.3.4.139' not in ips16

    # 不带结尾点也应按同一网段处理
    assert core.iter_scan_ip('10.3.4', '10.3.4.139') == ips


def test_parse_target_line():
    t = core.parse_target_line('10.3.4.139')
    assert (t.ip, t.port, t.scheme) == ('10.3.4.139', None, 'http')
    t = core.parse_target_line('10.3.4.139:8080')
    assert (t.ip, t.port) == ('10.3.4.139', 8080)
    t = core.parse_target_line('http://10.3.4.139:8080')
    assert (t.ip, t.port) == ('10.3.4.139', 8080)
    t = core.parse_target_line('https://10.3.4.139')
    assert t.scheme == 'https' and t.line == 'https://10.3.4.139'
    t = core.parse_target_line('10.3.4.139,9000')
    assert t.port == 9000
    t = core.parse_target_line('10.3.4.139 # note')
    assert t.ip == '10.3.4.139'
    for bad in ('1.2.3.4:0', '1.2.3.4,99999', 'x', '1.2.3', '1.2.3.4:abc',
                'ftp://1.2.3.4'):
        assert core.parse_target_line(bad) is None


def test_parse_targets_text():
    targets, bad = core.parse_targets_text(
        '10.0.0.1\n10.0.0.1\n10.0.0.2:8080\nbad\n# c\n')
    assert [t.line for t in targets] == ['10.0.0.1', '10.0.0.2:8080']
    assert bad == ['bad']

    # 畸形 URL 不能让解析器抛异常
    assert core.parse_target_line('http://[::1') is None
    targets, bad = core.parse_targets_text('http://[::1\n10.0.0.1')
    assert [t.line for t in targets] == ['10.0.0.1']
    assert bad == ['http://[::1']


def test_apply_target_and_base():
    t = core.Target('10.0.0.5', 8080)
    assert core.apply_target('http://127.0.0.1/shell.php', t) == \
        'http://10.0.0.5:8080/shell.php'
    assert core.apply_target('http://127.0.0.1:9000/shell.php', t) == \
        'http://10.0.0.5:9000/shell.php'
    assert core.base_from_url('http://127.0.0.1/shell.php', t) == \
        'http://10.0.0.5:8080'
    assert core.base_default(core.Target('10.0.0.5', 80)) == 'http://10.0.0.5'
    assert core.base_default(core.Target('10.0.0.5', 8080)) == \
        'http://10.0.0.5:8080'
    assert core.modify_host('https://u:p@127.0.0.1:8443/x.php',
                            '10.0.0.5') == 'https://u:p@10.0.0.5:8443/x.php'
    assert core.format_target('10.0.0.5', 80) == '10.0.0.5'
    assert core.format_target('10.0.0.5', 443) == '10.0.0.5:443'
    assert core.format_target('10.0.0.5', 8080) == '10.0.0.5:8080'


def test_apply_target_bad_port():
    with pytest.raises(ValueError):
        core.apply_target('http://127.0.0.1:abc/shell.php',
                          core.Target('10.0.0.1'))


# ---------------------------------------------------------------- 配置 / payload
def test_busima_default_matches_pass_and_quotes():
    code = config.busima_default()
    md5 = hashlib.md5(config.木马的pass密码.encode('utf-8')).hexdigest()
    assert md5 in code
    assert '$_POST["%s"]' % config.木马密码 in code
    assert '$_POST[a]' not in code
    assert "$file = __DIR__ . '/%s';" % config.木马文件名.split('/')[-1] in code


def test_busima_default_escapes():
    config.木马的pass密码 = "p'@ss"
    config.木马密码 = 'a"b'
    config.木马文件名 = 'upload/a b.php'
    code = config.busima_default()
    assert '$_POST["a\\"b"]' in code
    assert "$file = __DIR__ . '/a b.php';" in code


def test_payloads():
    code = '<?php echo "中文"; ?>'
    php = core.build_payload_php(code, '/var/www/html/upload/.data.php')
    assert 'file_put_contents' in php and 'mkdir' in php
    encoded = re.search(r"base64_decode\('([^']+)'\)", php).group(1)
    assert base64.b64decode(encoded).decode('utf-8') == code

    shell = core.build_payload_shell(code, '/tmp/a b.php')
    assert "'> /tmp/a b.php'" not in shell  # shlex.quote 会把整个路径包起来
    encoded = re.search(r'echo (\S+)\|base64 -d', shell).group(1)
    assert base64.b64decode(encoded).decode('utf-8') == code

    php_shell = core.build_payload_php_shell(code, '/tmp/a.php')
    assert 'system(base64_decode' in php_shell


def test_extract_flag():
    assert core.extract_flag(
        'angelkat\nWarning: x\nflag{abc_123}\nangelkat') == 'flag{abc_123}'
    assert core.extract_flag('angelkat\nplainflag\nangelkat') == 'plainflag'
    assert core.extract_flag('angelkat\nWarning: x\nangelkat') is None
    assert core.extract_flag('\x1b[31mflag{ansi}\x1b[0m') == 'flag{ansi}'
    assert core.extract_flag('') is None
    # 命令输出不能被当成 flag
    assert core.extract_flag('angelkat\nuid=0(root) gid=0(root)\nangelkat') is None
    assert core.extract_flag('angelkat\nindex.php\ntotal 0\nangelkat') is None
    # 无大括号但像 token 的旧式 flag 仍可识别
    assert core.extract_flag(
        'angelkat\n0123456789abcdef0123456789abcdef\nangelkat') == \
        '0123456789abcdef0123456789abcdef'
    # 状态占位符不是 flag
    assert core.extract_flag('angelkat\nnot_started\nangelkat') is None
    assert core.extract_flag('not_started') is None
    assert core.extract_flag('NOT_STARTED') is None


def test_parse_flag_text():
    flags = core.parse_flag_text('flag{a}\nxx flag{b} yy\nflag{a}\nplainflag')
    assert flags == ['flag{a}', 'flag{b}', 'plainflag']
    assert core.parse_flag_text('not_started') == []
    assert core.parse_flag_text('0123456789abcdef0123456789abcdef') == [
        '0123456789abcdef0123456789abcdef']


def test_fetch_flag_detail_status_placeholder():
    session = FakeSession(FakeResponse('not_started'))
    flag, detail, path = core.fetch_flag_detail(
        session, 'http://a', 'cat /flag')
    assert flag is None
    assert 'not_started' in detail
    assert path == ''


# ---------------------------------------------------------------- 报文 / 提交
def test_parse_http_request():
    raw = ('POST /api/flag HTTP/1.1\r\nHost: 10.0.0.1:8000\r\n'
           'content-type: application/json\r\nX-Test: 1\r\n\r\n{"a":1}')
    method, url, headers, body = core.parse_http_request(raw)
    assert method == 'POST'
    assert url == 'http://10.0.0.1:8000/api/flag'
    assert headers['X-Test'] == '1'
    assert body == '{"a":1}'
    assert core._header_value(headers, 'Content-Type') == 'application/json'


def test_parse_http_request_absolute_and_folded():
    raw = ('GET https://example.com/x HTTP/1.1\r\nHost: example.com\r\n'
           'X-Long: a\r\n  b\r\n\r\n')
    method, url, headers, body = core.parse_http_request(raw)
    assert method == 'GET'
    assert url == 'https://example.com/x'
    assert headers['X-Long'] == 'a b'
    assert body == ''


def test_parse_http_request_errors():
    with pytest.raises(ValueError):
        core.parse_http_request('')
    with pytest.raises(ValueError):
        core.parse_http_request('GET / HTTP/1.1\r\n\r\n')
    with pytest.raises(ValueError):
        core.parse_http_request('not a request')


def test_http_scheme_inference():
    raw = ('POST /s HTTP/1.1\r\nHost: platform.example\r\n'
           'Origin: https://platform.example\r\n\r\n')
    method, url, headers, body = core.parse_http_request(raw)
    assert url.startswith('https://')
    assert core.prepare_submission(raw).url.startswith('https://')

    raw = ('POST /s HTTP/1.1\r\nHost: platform.example\r\n'
           'Referer: http://platform.example/x\r\n\r\n')
    assert core.prepare_submission(raw).url.startswith('http://')

    raw = ('POST /s HTTP/1.1\r\nHost: platform.example\r\n'
           'X-Forwarded-Proto: https\r\n\r\n')
    assert core.prepare_submission(raw).url.startswith('https://')

    raw = 'POST /s HTTP/1.1\r\nHost: platform.example:443\r\n\r\n'
    assert core.prepare_submission(raw).url.startswith('https://')


def test_forced_submit_scheme(temp_config):
    raw = 'POST /s HTTP/1.1\r\nHost: 10.0.0.1\r\n\r\n'
    config.提交协议 = 'https'
    assert core.prepare_submission(raw).url.startswith('https://')
    config.提交协议 = 'http'
    assert core.prepare_submission(raw).url.startswith('http://')


def test_prepare_submission():
    form = ('POST /s HTTP/1.1\r\nHost: a\r\n'
            'Content-Type: application/x-www-form-urlencoded\r\n\r\nflag=old&x=1')
    sub = core.prepare_submission(form)
    assert sub.is_form and not sub.is_json

    js = ('POST /s HTTP/1.1\r\nHost: a\r\n'
          'content-type: Application/JSON\r\n\r\n{"flag":"x"}')
    sub = core.prepare_submission(js)
    assert sub.is_json and not sub.is_form

    multipart = ('POST /s HTTP/1.1\r\nHost: a\r\n'
                 'Content-Type: multipart/form-data; boundary=x\r\n\r\n--x--')
    with pytest.raises(ValueError):
        core.prepare_submission(multipart)


def test_form_body_replaces_and_encodes():
    body = core._form_body('foo=1&flag=old&bar=2', 'flag', 'flag{a+b/c==}')
    assert 'flag=old' not in body
    assert 'foo=1' in body and 'bar=2' in body
    assert body.endswith('flag=flag%7Ba%2Bb%2Fc%3D%3D%7D')


def test_submit_form():
    raw = ('POST /s HTTP/1.1\r\nHost: 10.0.0.1\r\n'
           'Content-Type: application/x-www-form-urlencoded\r\n'
           'Content-Length: 99\r\nX-Test: 1\r\n\r\nfoo=1&flag=old')
    session = FakeSession()
    core.submit_flag_ex(session, raw, 'flag{a+b/c==}', 'flag')
    method, args, kwargs = session.calls[-1]
    assert method == 'POST'
    assert 'Content-Length' not in kwargs['headers']
    assert kwargs['headers']['X-Test'] == '1'
    assert kwargs['data'] == 'foo=1&flag=flag%7Ba%2Bb%2Fc%3D%3D%7D'


def test_submit_get_and_json():
    session = FakeSession()
    core.submit_flag_ex(
        session, 'GET /s?x=1 HTTP/1.1\r\nHost: a\r\n\r\n', 'flag{g}', 'flag')
    method, args, kwargs = session.calls[-1]
    assert method == 'GET'
    assert kwargs['params'] == {'flag': 'flag{g}'}

    js = ('POST /s HTTP/1.1\r\nHost: a\r\n'
          'content-type: application/json\r\n\r\n{"a":1}')
    core.submit_flag_ex(session, js, 'flag{j}', 'flag')
    method, args, kwargs = session.calls[-1]
    assert kwargs['json'] == {'a': 1, 'flag': 'flag{j}'}

    with pytest.raises(ValueError):
        core.submit_flag_ex(
            session, 'POST /s HTTP/1.1\r\nHost: a\r\n'
                     'Content-Type: application/json\r\n\r\n[1,2]',
            'flag{j}', 'flag')


def test_submit_put_json():
    raw = ('PUT /s HTTP/1.1\r\nHost: a\r\n'
           'Content-Type: application/json\r\n\r\n{"a":1}')
    session = FakeSession()
    core.submit_flag_ex(session, raw, 'flag{p}', 'flag')
    method, args, kwargs = session.calls[-1]
    assert method == 'PUT'
    assert kwargs['json'] == {'a': 1, 'flag': 'flag{p}'}


def test_judge_submission():
    assert core.judge_submission(FakeResponse('{"code":0,"msg":"ok"}'))[0] == \
        'success'
    assert core.judge_submission(FakeResponse('{"code":1,"msg":"bad"}'))[0] == \
        'fail'
    assert core.judge_submission(FakeResponse('{"success":true}'))[0] == \
        'success'
    assert core.judge_submission(FakeResponse('{"success":1}'))[0] == 'success'
    assert core.judge_submission(FakeResponse('{"success":0}'))[0] == 'fail'
    assert core.judge_submission(FakeResponse('{"status":200}'))[0] == 'success'
    assert core.judge_submission(FakeResponse('{"status":"ok"}'))[0] == \
        'success'
    assert core.judge_submission(FakeResponse('{"foo":1}'))[0] == 'unknown'
    assert core.judge_submission(FakeResponse('denied', 403))[0] == 'fail'
    assert core.judge_submission(FakeResponse('all good'), 'good')[0] == \
        'success'
    assert core.judge_submission(FakeResponse('nope'), 'good')[0] == 'fail'

    verdict, detail = core.judge_submission(FakeResponse('platform says no', 200))
    assert verdict == 'unknown'
    assert 'platform says no' in detail
    verdict, detail = core.judge_submission(FakeResponse('denied', 403))
    assert verdict == 'fail'
    assert 'denied' in detail
    verdict, detail = core.judge_submission(FakeResponse('nope'), 'good')
    assert verdict == 'fail'
    assert 'nope' in detail


def test_judge_success_compat():
    assert core.judge_success('anything') is None
    assert core.judge_success('all good', 'good') is True


def test_classify_error():
    assert core.classify_error(requests.exceptions.ConnectTimeout()) == '超时'
    assert core.classify_error(requests.exceptions.ConnectionError()) == '连接失败'
    assert 'ValueError' in core.classify_error(ValueError('x'))


# ---------------------------------------------------------------- 批处理 / 扫描
def test_run_batch():
    results = core.run_batch(list(range(10)), lambda x: x * 2, workers=4)
    got = {item: result for item, result, error in results}
    assert got == {i: i * 2 for i in range(10)}
    assert all(error is None for _, _, error in results)
    assert core.run_batch([], lambda x: x) == []


def test_run_batch_stop():
    state = {'n': 0}

    def stop():
        state['n'] += 1
        return state['n'] > 3

    results = core.run_batch(list(range(50)), lambda x: x, workers=2,
                             stop=stop)
    assert 0 <= len(results) <= 3


def test_scan_hosts_invalid_prefix():
    assert core.scan_hosts('bad', '1.2.3.4') == []
    assert core.scan_hosts('', '') == []


# ---------------------------------------------------------------- 写马 / 命令 / flag
def test_write_busima_ex_ok(temp_config):
    config.不死马路径 = '/tmp/.data.php'
    config.运行的不死马路径 = 'upload/.data.php'
    config.木马文件名 = 'upload/-.php'
    session = ShellSession()
    ok, detail = core.write_busima_ex(session, core.Target('10.0.0.1'), {
        'url': 'http://127.0.0.1/shell.php',
        'url_type': '代码执行',
        'pass_type': 'POST传参密码',
        'pass_word': 'cmd',
        'code': '<?php echo 1; ?>',
    })
    assert ok, detail
    methods = [c[0] for c in session.calls]
    assert 'POST' in methods and 'GET' in methods
    first = session.calls[0]
    assert first[0] == 'POST'
    assert first[1][0] == 'http://10.0.0.1/shell.php'
    assert 'file_put_contents' in first[2]['data']['cmd']


def test_parse_headers():
    headers = core.parse_headers(
        'X-Forwarded-For: 127.0.0.1 | Cookie: a=1; b=2\nReferer: http://x')
    assert headers['X-Forwarded-For'] == '127.0.0.1'
    assert headers['Cookie'] == 'a=1; b=2'
    assert headers['Referer'] == 'http://x'
    assert core.parse_headers({'X-Test': '1'}) == {'X-Test': '1'}
    assert core.parse_headers('') == {}
    assert core.parse_headers('no colon line') == {}


def test_write_busima_ex_sends_headers(temp_config):
    config.不死马路径 = '/tmp/.data.php'
    config.运行的不死马路径 = 'upload/.data.php'
    config.木马文件名 = 'upload/-.php'
    session = ShellSession()
    ok, detail = core.write_busima_ex(session, core.Target('10.0.0.1'), {
        'url': 'http://127.0.0.1/shell.php',
        'url_type': '代码执行',
        'pass_type': 'POST传参密码',
        'pass_word': 'cmd',
        'headers': {'X-Test': '1', 'Cookie': 'a=1'},
        'code': '<?php echo 1; ?>',
    })
    assert ok, detail
    assert any(call[2].get('headers') == {'X-Test': '1', 'Cookie': 'a=1'}
               for call in session.calls)


def test_write_busima_ex_fail(temp_config):
    config.不死马路径 = '/tmp/.data.php'
    config.木马文件名 = 'upload/-.php'
    ok, detail = core.write_busima_ex(FakeSession(), core.Target('10.0.0.1'), {
        'url': 'http://127.0.0.1/shell.php',
        'url_type': '命令执行',
        'pass_type': 'POST传参密码',
        'pass_word': 'cmd',
        'code': '<?php echo 1; ?>',
    })
    assert not ok
    assert '验证失败' in detail
    assert '写入路径' in detail
    assert '入口请求' in detail
    assert '触发请求' in detail


def test_write_busima_ex_command_mode(temp_config):
    config.不死马路径 = '/tmp/.data.php'
    config.运行的不死马路径 = 'upload/.data.php'
    config.木马文件名 = 'upload/-.php'
    session = ShellSession()
    ok, detail = core.write_busima_ex(session, core.Target('10.0.0.1'), {
        'url': 'http://127.0.0.1/shell.php',
        'url_type': '命令执行',
        'pass_type': 'GET传参密码',
        'pass_word': 'cmd',
        'code': '<?php echo 1; ?>',
    })
    assert ok, detail
    first = session.calls[0]
    assert first[0] == 'GET'
    payload = first[2]['params']['cmd']
    assert 'base64 -d' in payload
    assert 'file_put_contents' not in payload


def test_write_busima_ex_bad_url(temp_config):
    ok, detail = core.write_busima_ex(FakeSession(), core.Target('10.0.0.1'), {
        'url': 'http://127.0.0.1:abc/shell.php',
        'url_type': '代码执行',
        'pass_type': 'POST传参密码',
        'pass_word': 'cmd',
        'code': '<?php echo 1; ?>',
    })
    assert not ok
    assert '端口' in detail


class OldShellSession(FakeSession):
    """只认 GET query 里的 pass 的旧模板"""

    def post(self, url, *args, **kwargs):
        self.calls.append(('POST', (url,), kwargs))
        if kwargs.get('params') and kwargs['params'].get('pass'):
            return FakeResponse('angelkatOKangelkat')
        return FakeResponse('')


def test_exec_php_old_get_pass_fallback():
    session = OldShellSession()
    text, error = core.exec_php(session, 'http://a', "echo 'angelkat';")
    assert error is None
    assert 'angelkat' in text
    assert len(session.calls) == 2


def test_verify_shell_old_get_pass_fallback():
    ok, detail = core.verify_shell(OldShellSession(), 'http://a', retries=1)
    assert ok, detail


def test_exec_helpers():
    session = FakeSession(FakeResponse('angelkatOKangelkat'))
    text, error = core.exec_php(session, 'http://a', "echo 'angelkat';")
    assert error is None and 'angelkat' in text
    assert core.check_shell(session, 'http://a')[0] is True

    session = FakeSession(FakeResponse('angelkatcmd outangelkat'))
    text, error = core.exec_shell(session, 'http://a', 'id')
    assert error is None and text == 'cmd out'


def test_fetch_flag_ex_custom_command():
    session = FakeSession(FakeResponse('angelkatflag{fake}angelkat'))
    flag, detail = core.fetch_flag_ex(session, 'http://a', 'cat /flag')
    assert flag == 'flag{fake}'
    assert 'ok' in detail


def test_fetch_flag_ex_native_fallback():
    session = NativeSession()
    flag, detail = core.fetch_flag_ex(session, 'http://a', 'cat /flag')
    assert flag == 'flag{native}'
    assert '原生' in detail


def test_fetch_flag_detail_path_cache():
    class PathSession(FakeSession):
        def post(self, url, *args, **kwargs):
            self.calls.append(('POST', (url,), kwargs))
            php = (kwargs.get('data') or {}).get(config.木马密码, '')
            if 'readfile' in php:
                return FakeResponse('angelkatPATH:/flag\nflag{path}angelkat')
            return FakeResponse('angelkat\nangelkat')

    session = PathSession()
    flag, detail, path = core.fetch_flag_detail(
        session, 'http://a', 'cat /flag', known_paths=['/flag'])
    assert flag == 'flag{path}'
    assert path == '/flag'
    assert '原生' in detail
    php = session.calls[-1][2]['data'][config.木马密码]
    assert 'PATH:' in php and '/flag' in php


FORM_RAW = ('POST /s HTTP/1.1\r\nHost: a\r\n'
            'Content-Type: application/x-www-form-urlencoded\r\n\r\nflag=x')


class FlakySession(FakeSession):
    def __init__(self, failures=1, status=0):
        super().__init__()
        self.failures = failures
        self.fail_status = status

    def post(self, *args, **kwargs):
        self.calls.append(('POST', args, kwargs))
        if self.failures:
            self.failures -= 1
            if self.fail_status:
                return FakeResponse('err', self.fail_status)
            raise requests.exceptions.ConnectionError()
        return FakeResponse('{"code":0}', 200)


def test_submit_retry_network():
    session = FlakySession(failures=1)
    resp = core.submit_flag_retry(
        session, FORM_RAW, 'flag{r}', 'flag', backoff=0)
    assert resp.status_code == 200
    assert len(session.calls) == 2


def test_submit_retry_5xx():
    session = FlakySession(failures=1, status=500)
    resp = core.submit_flag_retry(
        session, FORM_RAW, 'flag{r}', 'flag', backoff=0)
    assert resp.status_code == 200
    assert len(session.calls) == 2


def test_submit_retry_no_429():
    session = FlakySession(failures=1, status=429)
    resp = core.submit_flag_retry(
        session, FORM_RAW, 'flag{r}', 'flag', backoff=0)
    assert resp.status_code == 429
    assert len(session.calls) == 1


def test_describe_submission():
    form = ('POST /s HTTP/1.1\r\nHost: 10.0.0.1\r\n'
            'Content-Type: application/x-www-form-urlencoded\r\n\r\n'
            'foo=1&flag=old')
    info = core.describe_submission(form, 'flag{p}', 'flag')
    assert info['method'] == 'POST'
    assert info['url'] == 'http://10.0.0.1/s'
    assert info['body'] == 'foo=1&flag=flag%7Bp%7D'

    js = ('POST /s HTTP/1.1\r\nHost: 10.0.0.1\r\n'
          'Content-Type: application/json\r\n\r\n{"a":1}')
    info = core.describe_submission(js, 'flag{p}', 'flag')
    assert '"flag": "flag{p}"' in info['body']

    get = 'GET /s?x=1 HTTP/1.1\r\nHost: 10.0.0.1\r\n\r\n'
    info = core.describe_submission(get, 'flag{p}', 'flag')
    assert 'x=1' in info['url']
    assert 'flag=flag%7Bp%7D' in info['url']


DEFENSE_OUTPUT = (
    '###WEBSHELL###\n/var/www/html/upload/a.php\n'
    '###RECENT###\n/var/www/html/x.php\n'
    '###PHPINI###\n'
    'disable_functions => no value => no value\n'
    'open_basedir => no value => no value\n'
    '###FLAGPERM###\n'
    '-rw-r--r-- 1 root root 32 Jan 1 00:00 /flag\n'
    'uid=0(root) gid=0(root)\n'
    '###UPLOAD###\n'
    '123 4 drwxrwxrwx 2 www-data www-data 4096 /var/www/html/upload\n'
    '###SUID###\n/usr/bin/passwd\n'
    '###CRON###\n* * * * * /tmp/a\n'
    '###SSHKEY###\nssh-rsa AAAAB3Nza\n'
    '###LISTEN###\nLISTEN 0 128 0.0.0.0:80\n'
    '###END###')


def test_defense_check():
    result = core.defense_check(FakeSession(FakeResponse(DEFENSE_OUTPUT)),
                                'http://a')
    levels = [f[0] for f in result['findings']]
    titles = [f[1] for f in result['findings']]
    assert '严重' in levels
    assert any('webshell' in title for title in titles)
    assert any('flag' in title for title in titles)
    assert any('root' in title for title in titles)
    report = core.defense_report(result, '10.0.0.1')
    assert '[严重]' in report
    assert '10.0.0.1' in report


def test_defense_check_empty():
    result = core.defense_check(FakeSession(FakeResponse('')), 'http://a')
    assert result['findings'][0][0] == '提示'


def test_rate_limiter():
    sleeps = []
    limiter = core.RateLimiter(0.5, clock=lambda: 0.0,
                               sleep=lambda seconds: sleeps.append(seconds))
    limiter.wait()
    limiter.wait()
    limiter.wait()
    assert sleeps == [0.5, 1.0]
    core.RateLimiter(0).wait()


def test_probe_target():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('127.0.0.1', 0))
    server.listen(1)
    port = server.getsockname()[1]
    target = core.Target('127.0.0.1', port)
    try:
        alive, detail = core.probe_target(target, timeout=1)
        assert alive is True
        assert '可连接' in detail
    finally:
        server.close()
    alive, detail = core.probe_target(target, timeout=0.2)
    assert alive is False
    assert '失败' in detail
