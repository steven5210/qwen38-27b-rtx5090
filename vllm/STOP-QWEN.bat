@echo off
title Stopping Qwen3.8-27B
wsl -d Ubuntu-26.04 -u root --cd "%~dp0" -- bash killall-vllm.sh
echo Stopped.
pause
