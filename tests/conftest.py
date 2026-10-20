# -*- coding: utf-8 -*-
import os
import sys

import pytest

TOOL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if TOOL not in sys.path:
    sys.path.insert(0, TOOL)

# 必须在 import PySide6 之前设置，否则离屏测试会尝试连接显示服务
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import config


@pytest.fixture()
def temp_config(tmp_path, monkeypatch):
    """把设置/状态/ip/日志都指到临时目录，避免污染真实文件"""
    monkeypatch.setattr(config, '设置文件', str(tmp_path / 'settings.json'))
    monkeypatch.setattr(config, '状态文件', str(tmp_path / 'state.json'))
    monkeypatch.setattr(config, 'IP文件', str(tmp_path / 'ip.txt'))
    monkeypatch.setattr(config, '日志目录', str(tmp_path / 'logs'))
    config.restore_defaults()
    yield tmp_path
    config.restore_defaults()


@pytest.fixture(scope='session')
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app
