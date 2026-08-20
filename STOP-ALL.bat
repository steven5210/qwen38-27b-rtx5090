@echo off
title STOP EVERYTHING (no restore)
echo Stopping ninfer, vLLM, and any builds. Nothing will be restarted.
wsl.exe -d Ubuntu-26.04 -u root -- bash /mnt/c/Users/StevenPC/Downloads/qwen38/stop-all.sh
pause
