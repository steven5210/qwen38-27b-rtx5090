#!/bin/bash
# rn1.sh -- configure + build the residency worktree (niced; production tree untouched).
M=/mnt/c/Users/StevenPC/Downloads/qwen38
{
echo "=== RN1 build $(date) ==="
nice -n 19 cmake -S /opt/ninfer/rn -B /opt/ninfer/rn/build -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON \
  -DCMAKE_CUDA_COMPILER=/usr/local/cuda-13.2/bin/nvcc 2>&1 | tail -3
nice -n 19 cmake --build /opt/ninfer/rn/build -j 8 2>&1 | tail -5 || { echo RN1_BUILD_FAILED; exit 1; }
for t in ninfer_tool_call_parser_test ninfer_openai_schema_test ninfer_anthropic_schema_test; do
  TB=$(find /opt/ninfer/rn/build -name "$t" -type f -executable | head -1)
  [ -n "$TB" ] && { echo "-- $t:"; "$TB" || { echo RN1_UNIT_FAILED; exit 1; }; }
done
git -C /opt/ninfer/rn add -A
git -C /opt/ninfer/rn -c user.name=steven5210 -c user.email=shuynh5210@msn.com commit -m "engine: retention-aware lane selection and LRU retained eviction" 2>&1 | tail -2
git -C /opt/ninfer/rn log --oneline -2
echo RN1_DONE
} > $M/logs/rn1.log 2>&1
