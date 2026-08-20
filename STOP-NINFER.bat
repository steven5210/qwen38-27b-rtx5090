@echo off
title Stop NINFER + restore vLLM
echo Stopping ninfer and restoring production vLLM (boot ~2 min)...
wsl.exe -d Ubuntu-26.04 -u root -- bash -c "pkill -9 -f ninfer-serve; sleep 5; nohup bash /mnt/c/Users/StevenPC/Downloads/qwen38/serve-wsl.sh >/dev/null 2>&1 & for i in $(seq 1 90); do sleep 5; curl -s -m 3 -o /dev/null http://127.0.0.1:8000/health && break; done; echo vLLM health:; curl -s -o /dev/null -w %{http_code} http://127.0.0.1:8000/health; echo."
pause
