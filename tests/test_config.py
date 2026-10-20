# -*- coding: utf-8 -*-
import hashlib

import config


def test_save_and_load(temp_config):
    assert config.save_settings({'任务并发': 12, '请求超时': 3.5}) is True
    assert config.任务并发 == 12
    config.任务并发 = 1
    config.请求超时 = 1.0
    assert config.load_settings() is True
    assert config.任务并发 == 12
    assert config.请求超时 == 3.5


def test_save_failure_keeps_globals(temp_config, monkeypatch):
    old = config.任务并发
    # 把设置文件指向一个目录，os.replace(file, dir) 会失败
    monkeypatch.setattr(config, '设置文件', str(temp_config))
    assert config.save_settings({'任务并发': 12}) is False
    assert config.任务并发 == old


def test_none_uses_default(temp_config):
    config.任务并发 = 99
    assert config.save_settings({'任务并发': None}) is True
    assert config.任务并发 == config._DEFAULTS['任务并发']


def test_restore_and_reset(temp_config):
    config.任务并发 = 12
    config.restore_defaults()
    assert config.任务并发 == config._DEFAULTS['任务并发']
    assert config.save_settings() is True
    assert (temp_config / 'settings.json').exists()
    assert config.reset_settings() is True
    assert not (temp_config / 'settings.json').exists()


def test_state_roundtrip(temp_config):
    data = {'last_flag': {'a': 'flag{x}'}, 'alive': ['a'], 'written': []}
    assert config.save_state(data) is True
    assert config.load_state() == data


def test_busima_md5_matches_pass():
    md5 = hashlib.md5(config.木马的pass密码.encode('utf-8')).hexdigest()
    assert md5 in config.busima_default()


def test_interval_and_dedup_roundtrip(temp_config):
    assert config.save_settings({'提交间隔': 0.5, '全局去重': True}) is True
    config.提交间隔 = 0.0
    config.全局去重 = False
    assert config.load_settings() is True
    assert config.提交间隔 == 0.5
    assert config.全局去重 is True


def test_submit_interval_and_dedup_coerce():
    assert config._coerce('提交间隔', '1.5') == 1.5
    assert config._coerce('提交间隔', 9) == config._DEFAULTS['提交间隔']
    assert config._coerce('全局去重', 'true') is True
    assert config._coerce('全局去重', '0') is False
    assert config._coerce('全局去重', False) is False


def test_busima_uses_dir():
    code = config.busima_default()
    assert "__DIR__" in code
