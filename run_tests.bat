@echo off
chcp 65001 >nul
set PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
python -m pytest -q tests
pause
