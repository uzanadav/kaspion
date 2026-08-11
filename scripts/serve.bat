@echo off
rem kaspion dashboard - double-click me (Windows). Keep this window open.
cd /d "%~dp0.."
set PYTHONUTF8=1
".venv\Scripts\python.exe" -m kaspion.serve
pause
