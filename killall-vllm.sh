#!/bin/bash
# Stop server + engine cores.
# TWO traps this avoids:
#  1) `pkill -f vllm` matches THIS SCRIPT's own name (killall-vllm.sh) -> script suicides
#     before it can wait for VRAM release. Use precise patterns + self-PID exclusion.
#  2) vLLM renames the engine subprocess to "VLLM::EngineCore" (uppercase) -> need -i.
MYPID=$$
killed=0
for pat in '/opt/qwen38/venv/bin/vllm' 'VLLM::' '/opt/qwen38/venv/bin/python'; do
  for pid in $(pgrep -if "$pat" 2>/dev/null); do
    if [ "$pid" != "$MYPID" ] && [ "$pid" != "$PPID" ]; then
      kill -9 "$pid" 2>/dev/null && killed=$((killed+1))
    fi
  done
done
echo "killed=$killed"
sleep 4
LEFT=$(pgrep -cif 'VLLM::|/opt/qwen38/venv/bin/vllm' 2>/dev/null || echo 0)
echo "procs_left=$LEFT"
for i in $(seq 1 24); do
  USED=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' ')
  if [ "${USED:-99999}" -lt 3000 ]; then echo "gpu_released=${USED}MiB"; break; fi
  sleep 5
done
exit 0
