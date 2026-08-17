@echo off
title Qwen3.8-27B Server (96K MAX-CONTEXT - single user, BARE DESKTOP required)
echo 96K context, ONE request slot. Desktop apps must use ^<700MB VRAM
echo (close Wallpaper Engine / Chrome / games) or speed collapses.
set CTX=98304
set UTIL=0.925
set SEQS=1
wsl -d Ubuntu-26.04 -u root --cd "%~dp0" -- bash -c "CTX=98304 UTIL=0.925 SEQS=1 bash serve-wsl.sh"
pause
