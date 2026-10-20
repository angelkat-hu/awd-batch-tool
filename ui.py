# -*- coding: utf-8 -*-
"""
AWD 工具 - 界面
=========================
基于 Tkinter 重写：布局更清晰、操作可中止、所有网络操作放到后台线程，
界面不会被卡住。

author : anglekat
"""

import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox

import config
import core
from get_ip import get_ip

# 直接运行 ui.py 时也能读到 settings.json（main.py 已读过也无妨）
config.load_settings()

# ---------------- 配色 ----------------
COLOR_BG = '#f4f6f9'
COLOR_CARD = '#ffffff'
COLOR_PRIMARY = '#2f6fed'
COLOR_SUCCESS = '#1e9e5a'
COLOR_DANGER = '#d9483b'
COLOR_TEXT = '#222831'
COLOR_MUTED = '#6b7280'

FONT = ('Microsoft YaHei UI', 9)
FONT_BOLD = ('Microsoft YaHei UI', 9, 'bold')
FONT_TITLE = ('Microsoft YaHei UI', 11, 'bold')
FONT_MONO = ('Consolas', 9)

DEFAULT_BUSIMA = config.busima_default()


class Win(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('AWD 批量工具  v3.1')
        self.configure(bg=COLOR_BG)
        self._center(940, 640)
        self._stop_flag = False
        self._msg_queue = queue.Queue()

        self._init_style()
        self._build()
        self._pump()
        self.protocol('WM_DELETE_WINDOW', self._on_close)

    # ---------------- 基础 ----------------
    def _center(self, width, height):
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = int((sw - width) / 2)
        y = int((sh - height) / 2)
        self.geometry('%dx%d+%d+%d' % (width, height, x, y))
        self.minsize(900, 600)

    def _init_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use('clam')
        except tk.TclError:
            pass
        style.configure('TFrame', background=COLOR_BG)
        style.configure('Card.TFrame', background=COLOR_CARD)
        style.configure('TLabel', background=COLOR_BG, foreground=COLOR_TEXT, font=FONT)
        style.configure('Card.TLabel', background=COLOR_CARD, foreground=COLOR_TEXT, font=FONT)
        style.configure('Title.TLabel', background=COLOR_CARD, foreground=COLOR_PRIMARY, font=FONT_TITLE)
        style.configure('Muted.TLabel', background=COLOR_CARD, foreground=COLOR_MUTED, font=FONT)
        style.configure('TButton', font=FONT, padding=(10, 6))
        style.configure('Primary.TButton', font=FONT_BOLD, padding=(10, 6))
        style.configure('TEntry', font=FONT)
        style.configure('TCombobox', font=FONT)
        style.configure('TProgressbar', troughcolor='#e5e7eb', background=COLOR_PRIMARY)
        style.configure('TNotebook', background=COLOR_BG, borderwidth=0)
        style.configure('TNotebook.Tab', font=FONT, padding=(16, 7))

    def _card(self, parent):
        frame = ttk.Frame(parent, style='Card.TFrame', padding=12)
        return frame

    # ---------------- 布局 ----------------
    def _build(self):
        root = ttk.Frame(self, style='TFrame', padding=12)
        root.pack(fill='both', expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)

        self._build_header(root)
        self._build_body(root)
        self._build_footer(root)

    def _build_header(self, parent):
        bar = self._card(parent)
        bar.grid(row=0, column=0, sticky='ew')
        bar.columnconfigure(5, weight=1)

        ttk.Label(bar, text='我的 IP：', style='Card.TLabel').grid(row=0, column=0, sticky='w')
        self.var_myip = tk.StringVar(value='127.0.0.1')
        ttk.Entry(bar, textvariable=self.var_myip, width=18).grid(row=0, column=1, padx=(0, 8))

        self.btn_scan = ttk.Button(bar, text='获取全场 IP', style='Primary.TButton', command=self.on_scan)
        self.btn_scan.grid(row=0, column=2, padx=(0, 8))

        ttk.Label(bar, text='进度：', style='Card.TLabel').grid(row=0, column=3, sticky='e')
        self.progress = ttk.Progressbar(bar, orient='horizontal', mode='determinate', length=180)
        self.progress.grid(row=0, column=4, padx=(6, 8), sticky='w')

        self.lbl_count = ttk.Label(bar, text='存活 0 台', style='Muted.TLabel')
        self.lbl_count.grid(row=0, column=5, sticky='w')
        return bar

    def _build_body(self, parent):
        body = ttk.Frame(parent, style='TFrame')
        body.grid(row=2, column=0, sticky='nsew', pady=(10, 10))
        body.columnconfigure(0, weight=1, uniform='col')
        body.columnconfigure(1, weight=1, uniform='col')
        body.rowconfigure(0, weight=1)

        self._build_left(body)
        self._build_right(body)

    def _build_left(self, parent):
        card = self._card(parent)
        card.grid(row=0, column=0, sticky='nsew', padx=(0, 6))
        card.columnconfigure(0, weight=1)
        card.rowconfigure(2, weight=1)

        ttk.Label(card, text='① 不死马代码', style='Title.TLabel').grid(row=0, column=0, sticky='w')
        ttk.Label(card, text='可自行修改，点击“保存代码”后生效',
                  style='Muted.TLabel').grid(row=1, column=0, sticky='w', pady=(2, 6))

        wrap = ttk.Frame(card, style='Card.TFrame')
        wrap.grid(row=2, column=0, sticky='nsew')
        wrap.columnconfigure(0, weight=1)
        wrap.rowconfigure(0, weight=1)

        self.txt_busima = tk.Text(wrap, wrap='none', font=FONT_MONO, undo=True,
                                  bg='#fbfcfe', fg=COLOR_TEXT, relief='flat',
                                  highlightthickness=1, highlightbackground='#d7dbe3')
        self.txt_busima.grid(row=0, column=0, sticky='nsew')
        self.txt_busima.insert('1.0', DEFAULT_BUSIMA)
        sb = ttk.Scrollbar(wrap, orient='vertical', command=self.txt_busima.yview)
        sb.grid(row=0, column=1, sticky='ns')
        self.txt_busima.configure(yscrollcommand=sb.set)

        ttk.Button(card, text='保存代码', command=self.on_save_code).grid(
            row=3, column=0, sticky='e', pady=(8, 0))
        return card

    def _build_right(self, parent):
        card = self._card(parent)
        card.grid(row=0, column=1, sticky='nsew', padx=(6, 0))
        card.columnconfigure(1, weight=1)

        ttk.Label(card, text='② 写入不死马', style='Title.TLabel').grid(
            row=0, column=0, columnspan=3, sticky='w')
        ttk.Label(card, text='木马地址会自动把主机名替换成目标 IP',
                  style='Muted.TLabel').grid(row=1, column=0, columnspan=3, sticky='w', pady=(2, 8))

        ttk.Label(card, text='木马 URL：', style='Card.TLabel').grid(row=2, column=0, sticky='w', pady=4)
        self.var_url = tk.StringVar(value='http://127.0.0.1/shell.php')
        ttk.Entry(card, textvariable=self.var_url).grid(row=2, column=1, columnspan=2, sticky='ew', pady=4)

        mode_row = ttk.Frame(card, style='Card.TFrame')
        mode_row.grid(row=3, column=0, columnspan=3, sticky='ew', pady=4)
        mode_row.columnconfigure(1, weight=1)
        mode_row.columnconfigure(3, weight=1)
        ttk.Label(mode_row, text='执行方式：', style='Card.TLabel').grid(
            row=0, column=0, sticky='w')
        self.cb_type = ttk.Combobox(mode_row, state='readonly',
                                    values=('代码执行', '命令执行'))
        self.cb_type.current(0)
        self.cb_type.grid(row=0, column=1, sticky='ew', padx=(0, 10))
        ttk.Label(mode_row, text='传参方式：', style='Card.TLabel').grid(
            row=0, column=2, sticky='w')
        self.cb_pass = ttk.Combobox(mode_row, state='readonly',
                                    values=('GET传参密码', 'POST传参密码'))
        self.cb_pass.current(1)
        self.cb_pass.grid(row=0, column=3, sticky='ew')

        ttk.Label(card, text='木马密码：', style='Card.TLabel').grid(row=4, column=0, sticky='w', pady=4)
        self.var_pass = tk.StringVar(value='cmd')
        ttk.Entry(card, textvariable=self.var_pass).grid(row=4, column=1, columnspan=2, sticky='ew', pady=4)

        self.btn_write = ttk.Button(card, text='一键写入不死马', style='Primary.TButton',
                                    command=self.on_write)
        self.btn_write.grid(row=5, column=0, columnspan=3, sticky='ew', pady=(12, 4))

        self.lbl_write = ttk.Label(card, text='', style='Muted.TLabel')
        self.lbl_write.grid(row=6, column=0, columnspan=3, sticky='w')

        ttk.Separator(card, orient='horizontal').grid(
            row=7, column=0, columnspan=3, sticky='ew', pady=12)

        ttk.Label(card, text='③ 提交 flag', style='Title.TLabel').grid(
            row=8, column=0, columnspan=3, sticky='w')
        ttk.Label(card, text='从 ip.txt 里逐台取 flag 并按报文提交',
                  style='Muted.TLabel').grid(row=9, column=0, columnspan=3, sticky='w', pady=(2, 8))

        ttk.Label(card, text='请求报文：', style='Card.TLabel').grid(row=10, column=0, sticky='nw', pady=4)
        wrap = ttk.Frame(card, style='Card.TFrame')
        wrap.grid(row=10, column=1, columnspan=2, sticky='nsew', pady=4)
        wrap.columnconfigure(0, weight=1)
        wrap.rowconfigure(0, weight=1)
        card.rowconfigure(10, weight=1)
        self.txt_request = tk.Text(wrap, height=5, wrap='none', font=FONT_MONO,
                                   bg='#fbfcfe', fg=COLOR_TEXT, relief='flat',
                                   highlightthickness=1, highlightbackground='#d7dbe3')
        self.txt_request.grid(row=0, column=0, sticky='nsew')
        sb = ttk.Scrollbar(wrap, orient='vertical', command=self.txt_request.yview)
        sb.grid(row=0, column=1, sticky='ns')
        self.txt_request.configure(yscrollcommand=sb.set)

        ttk.Label(card, text='参数名：', style='Card.TLabel').grid(row=11, column=0, sticky='w', pady=4)
        self.var_param = tk.StringVar(value='flag')
        ttk.Entry(card, textvariable=self.var_param).grid(row=11, column=1, columnspan=2, sticky='ew', pady=4)

        ttk.Label(card, text='取 flag 命令：', style='Card.TLabel').grid(row=12, column=0, sticky='w', pady=4)
        self.var_cmd = tk.StringVar(value='cat /flag')
        ttk.Entry(card, textvariable=self.var_cmd).grid(row=12, column=1, columnspan=2, sticky='ew', pady=4)

        self.btn_submit = ttk.Button(card, text='一键提交 flag', style='Primary.TButton',
                                     command=self.on_submit)
        self.btn_submit.grid(row=14, column=0, columnspan=3, sticky='ew', pady=(12, 4))
        return card

    def _build_footer(self, parent):
        card = self._card(parent)
        card.grid(row=3, column=0, sticky='ew')
        card.columnconfigure(0, weight=1)
        card.rowconfigure(1, weight=1)

        head = ttk.Frame(card, style='Card.TFrame')
        head.grid(row=0, column=0, sticky='ew')
        head.columnconfigure(1, weight=1)
        ttk.Label(head, text='输出', style='Title.TLabel').grid(row=0, column=0, sticky='w')
        self.lbl_status = ttk.Label(head, text='就绪', style='Muted.TLabel')
        self.lbl_status.grid(row=0, column=1, sticky='w', padx=10)
        ttk.Button(head, text='停止', command=self.on_stop).grid(row=0, column=2, padx=(0, 6))
        ttk.Button(head, text='清空', command=self.on_clear).grid(row=0, column=3)

        wrap = ttk.Frame(card, style='Card.TFrame')
        wrap.grid(row=1, column=0, sticky='nsew', pady=(8, 0))
        wrap.columnconfigure(0, weight=1)
        wrap.rowconfigure(0, weight=1)

        self.txt_out = tk.Text(wrap, height=8, wrap='word', font=FONT_MONO,
                               bg='#1e2229', fg='#e6e6e6', insertbackground='#e6e6e6',
                               relief='flat', highlightthickness=0, state='disabled')
        self.txt_out.grid(row=0, column=0, sticky='nsew')
        sb = ttk.Scrollbar(wrap, orient='vertical', command=self.txt_out.yview)
        sb.grid(row=0, column=1, sticky='ns')
        self.txt_out.configure(yscrollcommand=sb.set)
        self.txt_out.tag_configure('ok', foreground='#5ddc8c')
        self.txt_out.tag_configure('fail', foreground='#ff7b72')
        self.txt_out.tag_configure('info', foreground='#8ab4ff')
        return card

    # ---------------- 界面线程安全 ----------------
    def log(self, text, tag=None):
        self._msg_queue.put(('log', text, tag))

    def set_status(self, text):
        self._msg_queue.put(('status', text, None))

    def set_progress(self, done, total):
        self._msg_queue.put(('progress', (done, total), None))

    def _pump(self):
        try:
            while True:
                kind, payload, tag = self._msg_queue.get_nowait()
                if kind == 'log':
                    self.txt_out.configure(state='normal')
                    self.txt_out.insert('end', payload + '\n', tag or '')
                    self.txt_out.see('end')
                    self.txt_out.configure(state='disabled')
                elif kind == 'status':
                    self.lbl_status.configure(text=payload)
                elif kind == 'progress':
                    done, total = payload
                    self.progress['maximum'] = max(total, 1)
                    self.progress['value'] = done
                    self.lbl_count.configure(text='扫描 %d/%d' % (done, total))
        except queue.Empty:
            pass
        self.after(80, self._pump)

    def _busy(self, flag):
        state = 'disabled' if flag else 'normal'
        for btn in (self.btn_scan, self.btn_write, self.btn_submit):
            btn.configure(state=state)

    # ---------------- 事件 ----------------
    def on_scan(self):
        my_ip = self.var_myip.get().strip()
        if not core.parse_ip_field(my_ip):
            messagebox.showerror('提示', '输入的 IP 地址有误')
            return
        self._stop_flag = False
        self._busy(True)
        self.set_status('正在扫描网段…')
        self.log('[扫描] 开始扫描 %s 所在网段' % my_ip, 'info')

        def worker():
            try:
                def progress(done, total):
                    self.set_progress(done, total)
                ip_list = get_ip(my_ip, progress, stop_flag=lambda: self._stop_flag)
                self.log('[扫描] 完成，存活 %d 台，已写入 ip.txt' % len(ip_list), 'ok')
                for ip in ip_list:
                    self.log('  ' + ip)
            except Exception as exc:
                self.log('[扫描] 失败：%s' % exc, 'fail')
            finally:
                self._busy(False)
                self.set_status('就绪')

        threading.Thread(target=worker, daemon=True).start()

    def on_save_code(self):
        code = self.txt_busima.get('1.0', 'end').rstrip('\n') + '\n'
        config.不死马代码 = code
        self.log('[配置] 不死马代码已保存（%d 字节）' % len(code), 'ok')

    def _collect_options(self):
        return {
            'url': self.var_url.get().strip(),
            'url_type': self.cb_type.get(),
            'pass_type': self.cb_pass.get(),
            'pass_word': self.var_pass.get().strip(),
            'code': self.txt_busima.get('1.0', 'end').rstrip('\n') + '\n',
        }

    def _read_ips(self):
        try:
            with open(config.IP文件, 'r', encoding='utf-8') as f:
                return [line.strip() for line in f if line.strip()]
        except OSError:
            return []

    def on_write(self):
        options = self._collect_options()
        if not options['url']:
            messagebox.showerror('提示', '请填写木马 URL')
            return
        ip_list = self._read_ips()
        if not ip_list:
            messagebox.showerror('提示', 'ip.txt 为空，请先获取全场 IP 或手动填写')
            return
        config.不死马代码 = options['code']
        self._stop_flag = False
        self._busy(True)
        self.set_status('正在批量写入不死马…')
        self.log('[写入] 目标 %d 台' % len(ip_list), 'info')

        def worker():
            session = core.build_session()
            ok = fail = 0
            try:
                for ip in ip_list:
                    if self._stop_flag:
                        self.log('[写入] 已停止', 'info')
                        break
                    if core.write_busima(session, ip, options):
                        ok += 1
                        self.log('[成功] %s 不死马已写入' % ip, 'ok')
                    else:
                        fail += 1
                        self.log('[失败] %s 写入失败' % ip, 'fail')
            except Exception as exc:  # noqa: BLE001
                self.log('[写入] 任务异常：%s' % exc, 'fail')
            finally:
                self.log('[写入] 结束：成功 %d，失败 %d' % (ok, fail), 'info')
                self._busy(False)
                self.set_status('就绪')

        threading.Thread(target=worker, daemon=True).start()

    def on_submit(self):
        raw = self.txt_request.get('1.0', 'end').strip()
        if not raw:
            messagebox.showerror('提示', '请填写提交 flag 的 HTTP 请求报文')
            return
        ip_list = self._read_ips()
        if not ip_list:
            messagebox.showerror('提示', 'ip.txt 为空，请先获取全场 IP 或手动填写')
            return
        cmd = self.var_cmd.get().strip()
        param = self.var_param.get().strip()
        url_template = self.var_url.get().strip()
        if not param:
            messagebox.showerror('提示', '请填写提交 flag 的参数名')
            return
        self._stop_flag = False
        self._busy(True)
        self.set_status('正在提交 flag…')
        self.log('[提交] 目标 %d 台' % len(ip_list), 'info')

        def worker():
            session = core.build_session()
            ok = fail = 0
            try:
                for ip in ip_list:
                    if self._stop_flag:
                        self.log('[提交] 已停止', 'info')
                        break
                    try:
                        base = (core.base_from_url(url_template, ip)
                                if url_template else core.base_default(ip))
                    except ValueError as exc:
                        fail += 1
                        self.log('[提交] %s URL 错误：%s' % (ip, exc), 'fail')
                        continue
                    flag = core.get_flag_at(session, base, cmd)
                    if not flag:
                        fail += 1
                        self.log('[失败] %s 未取到 flag' % ip, 'fail')
                        continue
                    self.log('[flag] %s => %s' % (ip, flag), 'info')
                    try:
                        resp = core.submit_flag_retry(session, raw, flag, param)
                        verdict, why = core.judge_submission(resp)
                        if verdict == 'success':
                            ok += 1
                            self.log('[提交] %s 成功' % ip, 'ok')
                        else:
                            fail += 1
                            self.log('[提交] %s %s：%s' % (
                                ip, '失败' if verdict == 'fail' else '未知', why),
                                'fail')
                    except Exception as exc:
                        fail += 1
                        self.log('[提交] %s 失败：%s' % (ip, exc), 'fail')
            except Exception as exc:  # noqa: BLE001
                self.log('[提交] 任务异常：%s' % exc, 'fail')
            finally:
                self.log('[提交] 结束：成功 %d，失败 %d' % (ok, fail), 'info')
                self._busy(False)
                self.set_status('就绪')

        threading.Thread(target=worker, daemon=True).start()

    def on_stop(self):
        self._stop_flag = True
        self.set_status('正在停止…')
        self.log('[控制] 已请求停止当前任务', 'info')

    def on_clear(self):
        self.txt_out.configure(state='normal')
        self.txt_out.delete('1.0', 'end')
        self.txt_out.configure(state='disabled')

    def _on_close(self):
        self._stop_flag = True
        self.destroy()


if __name__ == '__main__':
    Win().mainloop()
