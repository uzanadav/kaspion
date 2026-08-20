@echo off
rem kaspion dashboard - double-click me (Windows). Keep this window open; closing it stops the server.
cd /d "%~dp0"
set PYTHONUTF8=1
if not exist ".tools\uv.exe" goto notinstalled
if not exist ".venv" goto notinstalled
".tools\uv.exe" run python -m kaspion.serve
pause
exit /b 0

:notinstalled
echo.
echo כספיון עדיין לא הותקן.
echo לחצו פעמיים על install.bat (באותה תיקייה) והריצו שוב.
echo.
pause
exit /b 1
