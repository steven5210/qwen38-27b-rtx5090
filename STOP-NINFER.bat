@echo off
title Stop NINFER + restore vLLM
wsl.exe -d Ubuntu-26.04 -u root -- bash /mnt/c/Users/StevenPC/Downloads/qwen38/stop-ninfer.sh
pause
