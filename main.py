# -*- coding: utf-8 -*-
"""
AWD 工具 - 程序入口
=========================
运行：python main.py
优先使用 PySide6 界面（ui_qt.py），未安装则回退到 tkinter 界面（ui.py）。

author : anglekat
"""

import sys

import config


def _have(module):
    try:
        __import__(module)
        return True
    except Exception:  # noqa: BLE001 - 依赖缺失/损坏都按“没有”处理，走兜底
        return False


def main():
    if not _have('requests'):
        print('缺少依赖 requests，请先执行：pip install requests')
        sys.exit(1)

    # 两种界面都先读设置，tkinter 版也才能用上 settings.json
    config.ensure_dirs()
    config.load_settings()

    if _have('PySide6'):
        import ui_qt
        sys.exit(ui_qt.run())

    print('未检测到 PySide6，使用 tkinter 界面（如需更美观的界面请：pip install PySide6）')
    from ui import Win
    Win().mainloop()


if __name__ == '__main__':
    main()
