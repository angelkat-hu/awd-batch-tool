# -*- coding: utf-8 -*-
import time

import pytest

import config
import core
import ui_qt


@pytest.fixture()
def window(temp_config, qapp):
    (temp_config / 'ip.txt').write_text(
        '10.0.0.1\n10.0.0.2:8080\n', encoding='utf-8')
    win = ui_qt.MainWindow()
    win.show()
    qapp.processEvents()
    yield win, temp_config
    win.close()
    qapp.processEvents()


def test_construct_pages(window):
    win, tmp = window
    assert win.stack.count() == 6
    assert win.windowTitle().endswith('v3.1')
    assert len(win._targets) == 2
    assert win.chips['targets'].text() == '2'
    assert win.tbl_flag.columnCount() == 4
    assert win.tbl_cmd.columnCount() == 4
    assert win.tbl_inventory.columnCount() == 5
    # 三张表都在
    assert win.tbl_write is not None
    assert win.tbl_flag is not None
    assert win.tbl_cmd is not None


def test_targets_parse_and_save(window):
    win, tmp = window
    win.txt_ips.setPlainText(
        '10.0.0.1\nbad-line\n10.0.0.1:8080\n10.0.0.1\n')
    targets = win._targets_from_text()
    assert [t.line for t in targets] == ['10.0.0.1', '10.0.0.1:8080']
    win.on_save_list()
    assert (tmp / 'ip.txt').read_text(encoding='utf-8') == \
        '10.0.0.1\n10.0.0.1:8080'
    assert 'bad-line' in win.txt_log.toPlainText()
    assert win.chips['targets'].text() == '2'


def test_settings_save_and_reset(window):
    win, tmp = window
    win.st_timeout.setText('3.5')
    win.st_scantimeout.setText('0.5')
    win.st_workers.setText('64')
    win.st_task_workers.setText('12')
    win.st_submit_workers.setText('4')
    win.st_interval.setText('0.5')
    win.chk_dedup.setChecked(True)
    win.st_port.setText('8080')
    win.st_okword.setText('success')
    win.sp_round.setValue(120)
    values = win._settings_values()
    assert values['请求超时'] == 3.5
    assert values['任务并发'] == 12
    assert values['提交并发'] == 4
    assert values['提交间隔'] == 0.5
    assert values['全局去重'] is True
    assert values['轮次秒数'] == 120
    assert values['目标端口'] == '8080'

    win.on_save_settings()
    assert config.请求超时 == 3.5
    assert config.任务并发 == 12
    assert config.提交并发 == 4
    assert config.提交间隔 == 0.5
    assert config.全局去重 is True
    assert config.轮次秒数 == 120
    assert config.目标端口 == '8080'
    assert (tmp / 'settings.json').exists()
    assert win.ed_port.text() == '8080'

    win.on_reset_settings()
    assert config.请求超时 == config._DEFAULTS['请求超时']
    assert config.任务并发 == config._DEFAULTS['任务并发']
    assert config.提交间隔 == config._DEFAULTS['提交间隔']
    assert config.全局去重 == config._DEFAULTS['全局去重']
    assert win.st_timeout.text() == str(config._DEFAULTS['请求超时'])


def test_settings_pass_change_warns(window):
    win, tmp = window
    old_md5 = config.busima_default()
    win.st_passcode.setText('brand-new-pass')
    win.on_save_settings()
    assert '载入默认代码' in win.txt_log.toPlainText()
    win.on_load_default_code()
    assert config.busima_default() != old_md5
    assert config.木马的pass密码 == 'brand-new-pass'
    assert 'brand-new-pass' not in win.txt_busima.toPlainText()  # 只放 md5


def test_progress_reset_and_log(window):
    win, tmp = window
    win.set_progress(3, 3)
    assert win.progress.format() == '3 / 3'
    win._on_done('测试', 1, 0)
    assert win.progress.value() == 0
    assert win.progress.format() == ''

    win.log('hello-log', 'ok')
    text = win.txt_log.toPlainText()
    assert 'hello-log' in text
    assert '[' in text and ']' in text
    assert (tmp / 'logs').exists()


def test_theme_toggle(window):
    win, tmp = window
    start = win._theme
    win.on_toggle_theme()
    assert win._theme != start
    assert win.cb_theme.currentIndex() in (0, 1)
    win.on_toggle_theme()
    assert win._theme == start


def test_auto_stop_and_preset(window):
    win, tmp = window
    win.on_auto_stop()
    assert win._auto_on is False
    assert win.lbl_countdown.text() == '未启动'

    win.cb_preset.setCurrentIndex(4)  # 找 flag
    assert 'flag' in win.txt_cmd.toPlainText()
    assert win.cb_cmd_mode.currentIndex() == 0


def test_auto_round_stats(window):
    win, tmp = window
    win._auto_on = True
    win._round_left = 120
    win._on_done('自动提交', 3, 1)
    text = win.lbl_countdown.text()
    assert '成功3' in text and '失败1' in text
    win._auto_on = False


def test_preview_text(window):
    win, tmp = window
    win.txt_request.setPlainText(
        'POST /submit HTTP/1.1\r\nHost: 10.0.0.1\r\n'
        'Content-Type: application/x-www-form-urlencoded\r\n\r\nflag=old')
    win.ed_param.setText('flag')
    text = win._preview_text()
    assert 'METHOD: POST' in text
    assert 'URL: http://10.0.0.1/submit' in text
    assert 'flag=flag%7BPREVIEW%7D' in text
    assert 'Content-Type' in text


def test_scan_done_fills_targets(window):
    win, tmp = window
    win.ed_port.setText('8080')
    win._on_scan_done(['10.1.1.1', '10.1.1.2'])
    assert '10.1.1.1:8080' in win.txt_ips.toPlainText()
    assert win._alive == {'10.1.1.1:8080', '10.1.1.2:8080'}
    assert win.chips['alive'].text() == '2'
    lines = (tmp / 'ip.txt').read_text(encoding='utf-8').splitlines()
    assert lines == ['10.1.1.1:8080', '10.1.1.2:8080']


def test_inventory_page(window):
    win, tmp = window
    assert win.stack.count() == 6
    win._last_flag['10.0.0.1'] = 'flag{a}'
    win._flag_path['10.0.0.1'] = '/flag'
    win._alive.add('10.0.0.1')
    win._written.add('10.0.0.1')
    win._submitted['10.0.0.1'] = 'flag{a}'
    win._update_chips()

    assert win.tbl_inventory.rowCount() == 2
    row0 = [win.tbl_inventory.item(0, c).text() for c in range(5)]
    assert row0[0] == '10.0.0.1'
    assert row0[1] == '存活'
    assert row0[2] == '是'
    assert row0[3] == '成功'
    assert 'flag{a}' in row0[4] and '/flag' in row0[4]
    row1 = [win.tbl_inventory.item(1, c).text() for c in range(5)]
    assert row1[0] == '10.0.0.2:8080'
    assert row1[1] == '—'


def test_close_saves_state_and_settings(window):
    win, tmp = window
    win._last_flag['10.0.0.1'] = 'flag{a}'
    win._submitted['10.0.0.1'] = 'flag{a}'
    win._flag_path['10.0.0.1'] = '/flag'
    win._alive.add('10.0.0.1')
    win.close()
    assert (tmp / 'state.json').exists()
    assert (tmp / 'settings.json').exists()
    import json
    state = json.loads((tmp / 'state.json').read_text(encoding='utf-8'))
    assert state['last_flag']['10.0.0.1'] == 'flag{a}'
    assert state['flag_path']['10.0.0.1'] == '/flag'
    assert state['alive'] == ['10.0.0.1']
    win.show()


def _wait_task(win, app, timeout=15):
    deadline = time.time() + timeout
    while win._thread is not None and time.time() < deadline:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    assert win._thread is None
    assert win._running is False


def test_write_task_runs(window, qapp, monkeypatch):
    win, tmp = window
    win.txt_ips.setPlainText('10.0.0.1')
    monkeypatch.setattr(
        core, 'write_busima_ex',
        lambda session, target, options: (True, 'ok'))
    win.on_write()
    _wait_task(win, qapp)
    assert win.tbl_write.rowCount() == 1
    assert win._written == {'10.0.0.1'}
    assert win._rows['write'][0][1] == '成功'
    assert win.progress.format() == ''


def test_write_task_reports_verification_failure(window, qapp, monkeypatch):
    win, tmp = window
    win.txt_ips.setPlainText('10.0.0.1')
    monkeypatch.setattr(
        core, 'write_busima_ex',
        lambda session, target, options: (False, '验证失败：404 路径不对'))
    win.on_write()
    _wait_task(win, qapp)
    row = win._rows['write'][0]
    assert row[1] == '失败'
    assert '404' in row[2]
    assert '10.0.0.1' not in win._written


def test_write_task_unwraps_legacy_nested_result(window, qapp, monkeypatch):
    win, tmp = window
    win.txt_ips.setPlainText('10.0.0.1')
    monkeypatch.setattr(
        core, 'write_busima_ex',
        lambda session, target, options:
        (True, (False, '验证失败：404 路径不对')))
    win.on_write()
    _wait_task(win, qapp)
    row = win._rows['write'][0]
    assert row[1] == '失败'
    assert '404' in row[2]
    assert '10.0.0.1' not in win._written


def test_submit_task_runs(window, qapp, monkeypatch):
    win, tmp = window
    win.txt_ips.setPlainText('10.0.0.1')
    win.txt_request.setPlainText(
        'POST /submit HTTP/1.1\r\nHost: 10.0.0.1\r\n'
        'Content-Type: application/x-www-form-urlencoded\r\n\r\nfoo=1')
    win.ed_param.setText('flag')
    monkeypatch.setattr(
        core, 'fetch_flag_detail',
        lambda session, base, cmd=None, timeout=None, known_paths=None:
        ('flag{ui}', 'ok', '/flag'))

    class Resp(object):
        text = '{"code":0,"msg":"ok"}'
        status_code = 200

    monkeypatch.setattr(core, 'submit_flag_ex', lambda *a, **k: Resp())
    win.on_submit()
    _wait_task(win, qapp)
    assert win.tbl_flag.rowCount() == 1
    assert win._last_flag['10.0.0.1'] == 'flag{ui}'
    assert win._submitted['10.0.0.1'] == 'flag{ui}'
    assert win._flag_path['10.0.0.1'] == '/flag'
    assert win._rows['flag'][0][2] == '成功'


def test_command_task_runs(window, qapp, monkeypatch):
    win, tmp = window
    win.txt_ips.setPlainText('10.0.0.1')
    win.txt_cmd.setPlainText('id')
    monkeypatch.setattr(
        core, 'exec_shell',
        lambda session, base, cmd, timeout=None: ('uid=0(root)', None))
    win.on_command()
    _wait_task(win, qapp)
    assert win.tbl_cmd.rowCount() == 1
    assert 'uid=0(root)' in win.tbl_cmd.item(0, 1).text()
    assert win._rows['command'][0][3] == '成功'


def test_health_task_runs(window, qapp, monkeypatch):
    win, tmp = window
    win.txt_ips.setPlainText('10.0.0.1')
    monkeypatch.setattr(
        core, 'check_shell',
        lambda session, base, timeout=None: (True, 'ok'))
    win.on_health()
    _wait_task(win, qapp)
    assert win.tbl_cmd.rowCount() == 1
    assert win._rows['command'][0][3] == '存活'
    assert '10.0.0.1' in win._alive


def test_defense_task_runs(window, qapp, monkeypatch):
    win, tmp = window
    win.txt_ips.setPlainText('10.0.0.1')
    monkeypatch.setattr(
        core, 'defense_check',
        lambda *a, **k: {'error': '', 'sections': {}, 'raw': '',
                         'findings': [('正常', '未发现明显风险', '')]})
    reports = []
    monkeypatch.setattr(win, '_show_report', lambda text: reports.append(text))
    win.on_defense()
    _wait_task(win, qapp)
    assert reports and '未发现明显风险' in reports[0]
    assert win.tbl_cmd.rowCount() == 1
    assert win._rows['command'][0][3] == '正常'


def test_global_dedup_skips_same_flag(window, qapp, monkeypatch):
    win, tmp = window
    win.txt_ips.setPlainText('10.0.0.1\n10.0.0.2')
    win.txt_request.setPlainText(
        'POST /submit HTTP/1.1\r\nHost: 10.0.0.1\r\n'
        'Content-Type: application/x-www-form-urlencoded\r\n\r\nfoo=1')
    win.ed_param.setText('flag')

    class Resp(object):
        text = '{"code":0}'
        status_code = 200

    monkeypatch.setattr(
        core, 'fetch_flag_detail',
        lambda *a, **k: ('flag{same}', 'ok', ''))
    monkeypatch.setattr(core, 'submit_flag_ex', lambda *a, **k: Resp())
    old_workers, old_dedup, old_interval = (
        config.提交并发, config.全局去重, config.提交间隔)
    config.提交并发, config.全局去重, config.提交间隔 = 1, True, 0.0
    try:
        win.on_submit()
        _wait_task(win, qapp)
    finally:
        config.提交并发, config.全局去重, config.提交间隔 = (
            old_workers, old_dedup, old_interval)
    marks = [row[2] for row in win._rows['flag']]
    assert marks.count('成功') == 1
    assert any(mark.startswith('跳过（重复') for mark in marks)
    assert len(win._submitted) == 1


def test_inbox_does_not_pollute_target_state(window, qapp, monkeypatch):
    win, tmp = window
    win.txt_request.setPlainText(
        'POST /submit HTTP/1.1\r\nHost: 10.0.0.1\r\n'
        'Content-Type: application/x-www-form-urlencoded\r\n\r\nfoo=1')
    win.ed_param.setText('flag')

    class Resp(object):
        text = '{"code":0}'
        status_code = 200

    monkeypatch.setattr(core, 'submit_flag_ex', lambda *a, **k: Resp())
    win.on_submit_inbox('flag{manual}')
    _wait_task(win, qapp)
    assert win.tbl_flag.rowCount() == 1
    assert win._rows['inbox'][0][1] == 'flag{manual}'
    assert 'flag{manual}' not in win._last_flag.values()
    assert 'flag{manual}' not in win._submitted.values()


def test_alive_task_runs(window, qapp, monkeypatch):
    win, tmp = window
    win.txt_ips.setPlainText('10.0.0.1\n10.0.0.2:8080')
    monkeypatch.setattr(
        core, 'probe_target',
        lambda target, timeout=None:
        (target.port == 8080, 'TCP %s:%s' % (target.ip, target.port)))
    win.on_test_alive()
    _wait_task(win, qapp)
    assert win._alive == {'10.0.0.2:8080'}
    assert win.chips['alive'].text() == '1'
    assert len(win._rows['alive']) == 2
    log = win.txt_log.toPlainText()
    assert '[存活]' in log
    assert '[不存活]' in log


def test_submit_response_kept(window, qapp, monkeypatch):
    win, tmp = window
    win.txt_ips.setPlainText('10.0.0.1')
    win.txt_request.setPlainText(
        'POST /submit HTTP/1.1\r\nHost: 10.0.0.1\r\n'
        'Content-Type: application/x-www-form-urlencoded\r\n\r\nfoo=1')
    win.ed_param.setText('flag')
    monkeypatch.setattr(
        core, 'fetch_flag_detail',
        lambda *a, **k: ('flag{ui}', 'ok', '/flag'))

    class Resp(object):
        text = '{"code":0,"msg":"ok"}'
        status_code = 200
        reason = 'OK'
        url = 'http://platform/submit'
        headers = {'Content-Type': 'application/json'}

    monkeypatch.setattr(core, 'submit_flag_ex', lambda *a, **k: Resp())
    win.on_submit()
    _wait_task(win, qapp)
    info = win._responses['10.0.0.1']
    assert info['status'] == 200
    assert 'code' in info['text']
    text = win._response_text('10.0.0.1', info)
    assert 'HTTP：200' in text
    assert 'Content-Type' in text
    assert 'code' in text
    win.on_copy_response_row(win.tbl_flag, 0)
    assert 'code' in qapp.clipboard().text()


def test_copy_flag_row_and_log(window, qapp):
    win, tmp = window
    win._fill_table(win.tbl_flag, [
        ('10.0.0.1', 'flag{a}', '成功', '12:00:00'),
    ])
    win.tbl_flag.selectRow(0)
    win.on_copy_flag()
    assert 'flag{a}' in qapp.clipboard().text()
    assert '10.0.0.1' in qapp.clipboard().text()

    win.txt_log.setPlainText('hello log')
    win.on_copy_log()
    assert 'hello log' in qapp.clipboard().text()


def test_cell_double_click_shows_text(window, monkeypatch):
    win, tmp = window
    win._fill_table(win.tbl_write, [('10.0.0.1', '成功', 'ok')])
    shown = []
    monkeypatch.setattr(
        win, '_show_text_dialog',
        lambda title, text: shown.append((title, text)))
    win.on_cell_double_clicked(win.tbl_write, 0, 2)
    assert shown
    assert shown[0][1] == 'ok'


def test_table_copy_without_dialog(window, qapp):
    win, tmp = window
    win._fill_table(win.tbl_flag, [
        ('10.0.0.1', 'flag{a}', '成功', '12:00'),
    ])
    win.tbl_flag.setCurrentCell(0, 1)
    win.tbl_flag.copy_cell()
    assert 'flag{a}' in qapp.clipboard().text()
    win.tbl_flag.selectRow(0)
    win.tbl_flag.copy_rows()
    assert '成功' in qapp.clipboard().text()
