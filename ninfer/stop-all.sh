#!/bin/bash
# stop-all.sh -- stop EVERYTHING (ninfer + vLLM + builds), restore NOTHING.
pkill -9 -x ninfer-serve 2>/dev/null
bash /mnt/c/Users/StevenPC/Downloads/qwen38/killall-vllm.sh 2>/dev/null
pkill -9 -f "ninja" 2>/dev/null
pkill -9 -f "cicc\|nvcc\|ptxas" 2>/dev/null
sleep 2
echo "--- survivors on 8000/8080 (should be empty):"
ss -ltn | grep -E ':(8000|8080) ' || echo "none"
echo "--- GPU:"
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader
echo "ALL STOPPED. Nothing restarted."
