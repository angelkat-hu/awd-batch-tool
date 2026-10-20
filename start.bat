@echo off
chcp 65001 >nul
python main.py
if errorlevel 1 pause
