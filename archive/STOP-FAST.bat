@echo off
title Stop fast server
wsl -d Ubuntu-26.04 -u root -- pkill -9 -f ninfer-serve
echo Fast server stopped (main server unaffected).
pause
