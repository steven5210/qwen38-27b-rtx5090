@echo off
setlocal enabledelayedexpansion
title Qwen3.8 quick ask (medium - the fast, accurate default)
cd /d "%~dp0"
if not "%~1"=="" (
  wsl -d Ubuntu-26.04 -u root --cd "%~dp0" -- /opt/qwen38/venv/bin/python ask-xhigh.py --effort medium --max-tokens 16384 %*
  echo. & pause & exit /b 0
)
echo ============================================================
echo   Qwen3.8-27B  QUICK ASK  (medium effort)
echo ============================================================
echo.
echo  Seconds, not minutes. Scored 24/24 where xhigh scored 9/24.
echo.
set "ATTACH="
set /p "ATTACH=File to attach (press Enter to skip): "
echo.
set "Q="
set /p "Q=> "
if "!Q!"=="" ( echo No question given. & pause & exit /b 1 )
echo.
if "!ATTACH!"=="" (
  wsl -d Ubuntu-26.04 -u root --cd "%~dp0" -- /opt/qwen38/venv/bin/python ask-xhigh.py --effort medium --max-tokens 16384 "!Q!"
) else (
  wsl -d Ubuntu-26.04 -u root --cd "%~dp0" -- /opt/qwen38/venv/bin/python ask-xhigh.py --effort medium --max-tokens 16384 --file "!ATTACH!" "!Q!"
)
echo. & pause
