@echo off
setlocal
title Qwen3.8 deep-think (xhigh)
if "%~1"=="" (
  echo Deep-think mode - one hard question at maximum reasoning effort.
  echo.
  echo   ASK-XHIGH.bat "why does this deadlock when two workers retry at once?"
  echo   ASK-XHIGH.bat --file C:\path\to\bug.py "find the race condition"
  echo.
  echo Expect 4-10 minutes. Use Cline on medium for normal work.
  pause & exit /b 0
)
wsl -d Ubuntu-26.04 -u root --cd "%~dp0" -- /opt/qwen38/venv/bin/python ask-xhigh.py %*
pause
