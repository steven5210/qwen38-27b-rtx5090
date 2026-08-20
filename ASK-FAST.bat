@echo off
setlocal enabledelayedexpansion
title Qwen quick ask (FAST server - boots in ~15s if nothing is running)
cd /d "%~dp0"
if not "%~1"=="" (
  wsl -d Ubuntu-26.04 -u root --cd "%~dp0" -- /opt/qwen38/venv/bin/python ask-xhigh.py --fast --effort medium --max-tokens 8192 %*
  echo. & pause & exit /b 0
)
echo ============================================================
echo   FAST ASK - uses whichever server is up; boots the
echo   lightweight one (~15s) if nothing is running.
echo ============================================================
echo.
set "Q="
set /p "Q=> "
if "!Q!"=="" ( echo Nothing asked. & pause & exit /b 1 )
echo.
wsl -d Ubuntu-26.04 -u root --cd "%~dp0" -- /opt/qwen38/venv/bin/python ask-xhigh.py --fast --effort medium --max-tokens 8192 "!Q!"
echo. & pause
