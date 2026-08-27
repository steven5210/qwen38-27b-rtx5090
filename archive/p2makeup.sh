#!/bin/bash
R=/mnt/c/Users/StevenPC/Downloads/qwen38
AK=$(cat $R/api-key.txt)
{
echo "=== P2 MAKEUP: cache-hit accuracy on patched ninfer $(date) ==="
bash $R/killall-vllm.sh >/dev/null 2>&1; sleep 8
nohup /opt/ninfer/src/build/apps/ninfer-serve /opt/ninfer/models/qwen3_8_27b_nvfp4.ninfer \
  --api-key "$AK" --max-context 106496 --kv-dtype int8 --max-concurrency 2 \
  --spec mtp --draft-tokens 3 --lm-head-draft \
  > /opt/ninfer/logs/mk.out 2> /opt/ninfer/logs/mk.err &
for i in $(seq 1 40); do sleep 3; curl -s -m 3 -o /dev/null -H "Authorization: Bearer $AK" http://127.0.0.1:8080/v1/models && break; done
cd $R && QWEN_URL=http://127.0.0.1:8080 /opt/qwen38/venv/bin/python -u cachehit-eval.py --samples 2 --effort medium --tag p2mk 2>&1 | tail -12
pkill -9 -f ninfer-serve; sleep 8
nohup bash $R/serve-wsl.sh >/dev/null 2>&1 &
for i in $(seq 1 90); do sleep 5; curl -s -m 3 -o /dev/null http://127.0.0.1:8000/health && break; done
sleep 12
head -c 18000000 $R/logs/serve.log | tr -d '\r' | grep -aoE "GPU KV cache size: [0-9,]+" | tail -1
echo "health=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health)"
echo P2MAKEUP_DONE
} > $R/logs/p2makeup.log 2>&1
