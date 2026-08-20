@echo off
title Qwen3.8-27B on NINFER (close this window to stop)
echo ============================================================
echo  Qwen3.8-27B NVFP4 on NINFER  -  RTX 5090
echo  Endpoint: http://127.0.0.1:8080/v1   model: qwen3.8-27b
echo  API key:  see api-key.txt in this folder
echo  Boot takes ~10 SECONDS. Config: ninfer-prod.conf
echo  CLOSING THIS WINDOW STOPS THE SERVER.
echo ============================================================
start "NINFER Monitor" /D "%~dp0" NMON.bat
wsl.exe -d Ubuntu-26.04 -u root -- bash /mnt/c/Users/StevenPC/Downloads/qwen38/ninfer-serve-prod.sh
pause
