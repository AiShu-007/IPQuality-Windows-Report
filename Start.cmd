@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist "runtime\python\python.exe" (
  echo Portable runtime missing. Download Windows-x64-Portable.zip from Releases and extract it completely.
  pause
  exit /b 2
)
"runtime\python\python.exe" -X utf8 launcher.py %*
set "IPQ_EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%IPQ_NO_PAUSE%"=="1" pause
exit /b %IPQ_EXIT_CODE%
