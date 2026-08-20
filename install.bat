@echo off
rem kaspion installer - double-click me (Windows). Run this once, then use kaspion.bat.
rem chcp 65001 puts the console in UTF-8 so the Hebrew progress messages are readable.
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install.ps1"
