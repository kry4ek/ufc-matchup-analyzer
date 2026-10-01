@echo off
setlocal
set "PYTHONUTF8=1"
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo Setup is missing. Run setup.bat first.
  if "%~1"=="" pause
  exit /b 1
)
"%~dp0.venv\Scripts\python.exe" "%~dp0ufc_matchup_analyzer.py" %*
set "ANALYZER_EXIT=%ERRORLEVEL%"
if "%~1"=="" pause
exit /b %ANALYZER_EXIT%
