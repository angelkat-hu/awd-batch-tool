# -*- coding: utf-8 -*-
"""
AWD 工具 - 旧接口兼容层
=========================
老版本把全部逻辑写在 自定义.py 里。为了不影响习惯旧入口的人，
这里保留同名函数，实际实现全部转发到 core.py。

新代码请直接使用 core.py。

author : anglekat
"""

# pylint: disable=unused-import
from core import (           # noqa: F401
    build_session,
    parse_ip_field,
    iter_scan_ip,
    scan_hosts,
    modify_host,
    build_payload,
    send_boom,
    write_busima,
    get_flag,
    parse_http_request,
    submit_flag,
)
from get_ip import get_ip    # noqa: F401


def set_busima(code):
    """旧接口：保存不死马代码"""
    import config
    config.不死马代码 = code
    print('设置不死马成功！')


def convert_http_to_requests(http_request, get_flag_cmd, flag_param):
    """
    旧接口：把原始报文转成 requests 调用。
    新实现不再拼接可执行代码，改为返回一个结构化描述，便于调试。
    """
    method, url, headers, body = parse_http_request(http_request)
    return {
        'method': method,
        'url': url,
        'headers': headers,
        'body': body,
        'flag_param': flag_param,
        'flag_value': get_flag_cmd,
    }
