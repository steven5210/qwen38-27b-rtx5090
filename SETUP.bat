@echo off
title Qwen3.8-27B Setup (RTX 5090)
echo ============================================================
echo  Qwen3.8-27B NVFP4 one-time setup
echo  Needs: RTX 5090 (or 32GB Blackwell), recent NVIDIA driver,
echo  ~60GB free on C:, internet. Takes 15-40 min (20GB download).
echo ============================================================
echo.
echo [1/3] Ubuntu-26.04 under WSL2...
wsl -d Ubuntu-26.04 -e true >nul 2>&1
if errorlevel 1 wsl --install -d Ubuntu-26.04 --no-launch
echo [2/3] WSL memory config...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-wslconfig.ps1"
echo [3/3] Provisioning packages + model inside WSL...
wsl -d Ubuntu-26.04 -u root --cd "%~dp0" -- bash setup-wsl.sh
echo.
echo Done. Next: double-click START-QWEN.bat
pause
