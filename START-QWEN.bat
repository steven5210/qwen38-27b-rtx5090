@echo off
title Qwen3.8-27B Server (96K validated profile - close window to stop)
echo Endpoint: http://127.0.0.1:8000/v1   model: qwen3.8-27b
echo Context : 96K, 1 request slot (the profile every benchmark in README.md was measured on)
echo API key : api-key.txt in this folder (auto-generated first run)
echo Boot ~2.5 min warm / ~5 min first time. Log: logs\serve.log
echo CLOSING THIS WINDOW STOPS THE SERVER.
wsl -d Ubuntu-26.04 -u root --cd "%~dp0" -- bash serve-wsl.sh
pause
