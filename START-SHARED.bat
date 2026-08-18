@echo off
title Qwen3.8-27B Server (shared: 60K context, 4 slots)
echo For two people / parallel agents. Lower context so 4 slots fit the KV pool.
echo Endpoint: http://127.0.0.1:8000/v1   model: qwen3.8-27b
echo CLOSING THIS WINDOW STOPS THE SERVER.
wsl -d Ubuntu-26.04 -u root --cd "%~dp0" -- bash -c "CTX=61440 SEQS=4 bash serve-wsl.sh"
pause
