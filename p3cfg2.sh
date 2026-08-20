#!/bin/bash
# p3cfg2.sh -- Option A refined: vision + 192,512 with slimmed media budgets (frees ~1.75 GiB
# for prefill workspace; the default budgets left only 491 MiB free and prefill ran 12x slow).
R=/mnt/c/Users/StevenPC/Downloads/qwen38
PY=/opt/qwen38/venv/bin/python
AK=$(cat $R/api-key.txt)
{
echo "=== P3CFG2 $(date) ==="
for i in $(seq 1 24); do
  RUN=$(curl -s -m 3 http://127.0.0.1:8000/metrics -H "Authorization: Bearer $AK" | grep -a "^vllm:num_requests_running" | awk '{s+=$2} END{print int(s)}')
  [ "${RUN:-0}" = "0" ] && break; sleep 10
done
bash $R/killall-vllm.sh >/dev/null 2>&1; pkill -9 -f ninfer-serve 2>/dev/null; sleep 5
nohup /opt/ninfer/src/build/apps/ninfer-serve /opt/ninfer/models/qwen3_8_27b_nvfp4.ninfer \
  --api-key "$AK" --max-context 192512 --kv-dtype int8 --max-concurrency 2 \
  --spec mtp --draft-tokens 3 --lm-head-draft --vision \
  --media-cache-mib 256 --media-live-mib 1024 \
  > /opt/ninfer/logs/p3cfg2.out 2> /opt/ninfer/logs/p3cfg2.err &
UP=0
for i in $(seq 1 30); do sleep 3; curl -s -m 3 -o /dev/null -H "Authorization: Bearer $AK" http://127.0.0.1:8080/v1/models && { UP=1; break; }; done
echo "up=$UP vram=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits)"
grep -aoE "free-after-startup=[0-9.]+ MiB|media-cache=[0-9.]+ GiB|media-live=[0-9.]+ GiB" /opt/ninfer/logs/p3cfg2.err | head -3
if [ "$UP" = "1" ]; then
  cd $R && TARGET_URL=http://127.0.0.1:8080/v1/chat/completions NEEDLE_SIZES=180000 $PY -u needleprobe.py 2>&1 | tail -2
  cd $R && QWEN_URL=http://127.0.0.1:8080 $PY -u vision-probe.py 2>&1 | tail -3
else
  echo "boot failed:"; tail -c 900 /opt/ninfer/logs/p3cfg2.err
fi
pkill -9 -f ninfer-serve; sleep 6
nohup bash $R/serve-wsl.sh >/dev/null 2>&1 &
for i in $(seq 1 90); do sleep 5; curl -s -m 3 -o /dev/null http://127.0.0.1:8000/health && break; done
sleep 12
head -c 18000000 $R/logs/serve.log | tr -d '\r' | grep -aoE "GPU KV cache size: [0-9,]+" | tail -1
echo "health=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health)"
echo P3CFG2_DONE
} > $R/logs/p3cfg2.log 2>&1
