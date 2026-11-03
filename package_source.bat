@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0package_source.ps1"
if errorlevel 1 goto :error
goto :eof

:error
echo.
echo SOURCE PACKAGING FAILED. Review the error above.
exit /b 1
