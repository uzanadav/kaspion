@echo off
rem kaspion uninstaller - double-click me (Windows).
rem Your financial data is only removed if you explicitly type DELETE when asked.
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\uninstall.ps1"
