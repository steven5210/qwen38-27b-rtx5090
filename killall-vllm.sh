#!/bin/bash
pkill -9 -f '/opt/qwen38/venv' 2>/dev/null
pkill -9 -f vllm 2>/dev/null
sleep 5
# block until VRAM actually releases (prevents overlap-boot crashes)
for i in $(seq 1 24); do
  USED=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' ')
  [ "${USED:-99999}" -lt 3000 ] && { echo "gpu_released=${USED}MiB"; break; }
  sleep 5
done
exit 0
