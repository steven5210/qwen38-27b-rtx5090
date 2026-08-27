#!/bin/bash
# p3cfg.sh -- validate the Phase 3 production config: vision + max context together.
R=/mnt/c/Users/StevenPC/Downloads/qwen38
PY=/opt/qwen38/venv/bin/python
AK=$(cat $R/api-key.txt)
try_cfg(){
  CTX=$1
  pkill -9 -f ninfer-serve 2>/dev/null; sleep 4
  nohup /opt/ninfer/src/build/apps/ninfer-serve /opt/ninfer/models/qwen3_8_27b_nvfp4.ninfer \
    --api-key "$AK" --max-context $CTX --kv-dtype int8 --max-concurrency 2 \
    --spec mtp --draft-tokens 3 --lm-head-draft --vision \
    > /opt/ninfer/logs/p3cfg.out 2> /opt/ninfer/logs/p3cfg.err &
  UP=0
  for i in $(seq 1 30); do sleep 3; curl -s -m 3 -o /dev/null -H "Authorization: Bearer $AK" http://127.0.0.1:8080/v1/models && { UP=1; break; }; done
  echo "ctx=$CTX up=$UP vram=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits)"
  if [ "$UP" = "1" ]; then
    grep -aiE "kv|capacity|pool" /opt/ninfer/logs/p3cfg.err /opt/ninfer/logs/p3cfg.out 2>/dev/null | head -4
    cd $R && TARGET_URL=http://127.0.0.1:8080/v1/chat/completions NEEDLE_SIZES=$2 $PY -u needleprobe.py 2>&1 | tail -3
    cd $R && QWEN_URL=http://127.0.0.1:8080 $PY -u vision-probe.py 2>&1 | tail -3
  else
    echo "boot failed; stderr tail:"; tail -c 1200 /opt/ninfer/logs/p3cfg.err
  fi
  return $((1-UP))
}
{
echo "=== P3CFG $(date) ==="
for i in $(seq 1 24); do
  RUN=$(curl -s -m 3 http://127.0.0.1:8000/metrics -H "Authorization: Bearer $AK" | grep -a "^vllm:num_requests_running" | awk '{s+=$2} END{print int(s)}')
  [ "${RUN:-0}" = "0" ] && break; sleep 10
done
bash $R/killall-vllm.sh >/dev/null 2>&1; sleep 5
echo "--- attempt 1: vision + 252,928"
if try_cfg 252928 236000; then CHOSEN=252928; else
  echo "--- attempt 2: vision + 192,512"
  if try_cfg 192512 180000; then CHOSEN=192512; else
    echo "--- attempt 3: vision + 152,576"
    try_cfg 152576 140000 && CHOSEN=152576 || CHOSEN=none
  fi
fi
echo "CHOSEN=$CHOSEN"
pkill -9 -f ninfer-serve; sleep 6
nohup bash $R/serve-wsl.sh >/dev/null 2>&1 &
for i in $(seq 1 90); do sleep 5; curl -s -m 3 -o /dev/null http://127.0.0.1:8000/health && break; done
sleep 12
head -c 18000000 $R/logs/serve.log | tr -d '\r' | grep -aoE "GPU KV cache size: [0-9,]+" | tail -1
echo "health=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health)"
echo P3CFG_DONE
} > $R/logs/p3cfg.log 2>&1
