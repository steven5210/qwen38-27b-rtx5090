#!/bin/bash
# stop-ninfer.sh -- stop the ninfer server and restore production vLLM.
R=/mnt/c/Users/StevenPC/Downloads/qwen38
pkill -9 -x ninfer-serve 2>/dev/null
sleep 5
echo "[stop-ninfer] ninfer stopped; booting production vLLM (~2 min)..."
nohup bash $R/serve-wsl.sh >/dev/null 2>&1 &
for i in $(seq 1 90); do sleep 5; curl -s -m 3 -o /dev/null http://127.0.0.1:8000/health && break; done
sleep 12
head -c 18000000 $R/logs/serve.log | tr -d '\r' | grep -aoE "GPU KV cache size: [0-9,]+" | tail -1
echo "vLLM health=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health)"
echo "[stop-ninfer] done."
