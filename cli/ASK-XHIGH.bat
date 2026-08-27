@echo off
setlocal enabledelayedexpansion
title Qwen3.8 deep-think (reasoning_effort = xhigh)
cd /d "%~dp0"

if not "%~1"=="" (
  rem  command-line mode:  ASK-XHIGH.bat "question"   /   ASK-XHIGH.bat --file x.py "question"
  wsl -d Ubuntu-26.04 -u root --cd "%~dp0" -- /opt/qwen38/venv/bin/python ask-xhigh.py %*
  echo.
  pause
  exit /b 0
)

echo ============================================================
echo   Qwen3.8-27B  DEEP-THINK  (xhigh, ~90,000 tokens of room)
echo ============================================================
echo.
echo  For ONE hard question. Expect 4-10 minutes.
echo  Use Cline on medium for normal coding - it is faster AND
echo  scored better on every test we ran.
echo.
echo  Optional: drop in a file path to attach it.
echo.

set "ATTACH="
set /p "ATTACH=File to attach (press Enter to skip): "

echo.
echo  Type your question, then press Enter:
echo.
set "Q="
set /p "Q=> "

if "!Q!"=="" (
  echo.
  echo  No question given. Nothing to do.
  pause
  exit /b 1
)

echo.
echo  Working. The thinking counter updates every 2 seconds...
echo ------------------------------------------------------------
if "!ATTACH!"=="" (
  wsl -d Ubuntu-26.04 -u root --cd "%~dp0" -- /opt/qwen38/venv/bin/python ask-xhigh.py "!Q!"
) else (
  wsl -d Ubuntu-26.04 -u root --cd "%~dp0" -- /opt/qwen38/venv/bin/python ask-xhigh.py --file "!ATTACH!" "!Q!"
)
echo ------------------------------------------------------------
echo.
pause
