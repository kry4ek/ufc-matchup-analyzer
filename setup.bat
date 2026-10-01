@echo off
setlocal
set "PYTHONUTF8=1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
set "ANALYZER_EXIT=%ERRORLEVEL%"
if "%~1"=="" pause
exit /b %ANALYZER_EXIT%
