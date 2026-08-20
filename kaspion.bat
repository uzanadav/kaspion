@echo off
rem kaspion dashboard - double-click me (Windows). Keep this window open; closing it stops the server.
rem chcp 65001 puts the console in UTF-8 so the Hebrew messages below are readable.
rem (No BOM on .bat files - cmd.exe mis-executes the first line when one is present.)
chcp 65001 >nul
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
