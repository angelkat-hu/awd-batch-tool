# -*- coding: utf-8 -*-
"""
AWD 工具 - 网段扫描入口
=========================
兼容旧入口 get_ip(ip, progress_callback)。
真正的扫描逻辑在 core.scan_hosts 里。

author : anglekat
"""

import config
import core


def get_ip(ip, jindu, stop_flag=None):
    """
    扫描指定网段里存活的机器，写入 ip.txt。
    ip      自己所在网段的 IP，例如 10.3.4.139
    jindu   进度回调，签名 jindu(done, total)
    """
    prefix = core.parse_ip_field(ip)
    if not prefix:
        raise ValueError('输入的 IP 地址有误')

    def progress(done, total):
        if jindu:
            try:
                jindu(done, total)
            except Exception:
                pass

    alive = core.scan_hosts(prefix, ip.strip(), progress=progress, stop_flag=stop_flag)
    with open(config.IP文件, 'w', encoding='utf-8') as f:
        f.write('\n'.join(alive))
    return alive
