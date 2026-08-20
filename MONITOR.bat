@echo off
title Qwen3.8-27B Monitor
wsl.exe -d Ubuntu-26.04 -u root --cd "%~dp0" -- python3 monitor.py
pause
