@echo off
rem kaspion dashboard - double-click me (Windows). Keep this window open; closing it stops the server.
rem chcp 65001 puts the console in UTF-8 so the Hebrew messages below are readable.
rem (No BOM on .bat files - cmd.exe mis-executes the first line when one is present.)
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
if not exist ".tools\uv.exe" goto notinstalled
if not exist ".venv" goto notinstalled
rem A browser cannot start a process, but it can open a URL. Registering this
rem kaspion:// handler (current user only, no admin) is what makes the dashboard's
rem "start kaspion" button work when the server is down. Idempotent, so it also
rem heals installs made before the button existed.
reg add "HKCU\Software\Classes\kaspion" /ve /d "URL:kaspion" /f >nul 2>&1
reg add "HKCU\Software\Classes\kaspion" /v "URL Protocol" /d "" /f >nul 2>&1
reg add "HKCU\Software\Classes\kaspion\shell\open\command" /ve /d "\"%~dp0kaspion.bat\"" /f >nul 2>&1
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
