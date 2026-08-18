@echo off
title Qwen3.8-27B Server (VISION profile - screenshots and mockups)
echo Vision tower ON. 96K context preserved (KV pool 99,580 tokens).
echo Cost vs the default profile: cached first-token ~5.3s instead of ~3.6s.
echo Use this only when you need to paste images; START-QWEN.bat is faster for pure coding.
echo Endpoint: http://127.0.0.1:8000/v1   model: qwen3.8-27b
echo CLOSING THIS WINDOW STOPS THE SERVER.
wsl -d Ubuntu-26.04 -u root --cd "%~dp0" -- bash -c "VISION=1 KV_BYTES=4400000000 bash serve-wsl.sh"
pause
