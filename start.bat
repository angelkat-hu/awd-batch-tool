@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist pass.txt set /p AWD_PASS=<pass.txt
python main.py
if errorlevel 1 pause
