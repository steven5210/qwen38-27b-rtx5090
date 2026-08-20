#!/bin/bash
# rn3.sh -- adopt residency commit into the production tree + rebuild. Running server untouched
# (binary inode held); takes effect at next START-NINFER.
M=/mnt/c/Users/StevenPC/Downloads/qwen38
{
echo "=== RN3 adopt $(date) ==="
cd /opt/ninfer/src
git cherry-pick 7bb6db7 2>&1 | tail -2
git log --oneline -5
nice -n 10 cmake --build /opt/ninfer/src/build -j 8 2>&1 | tail -3 || { echo RN3_BUILD_FAILED; exit 1; }
for t in ninfer_tool_call_parser_test ninfer_openai_schema_test ninfer_anthropic_schema_test; do
  TB=$(find /opt/ninfer/src/build -name "$t" -type f -executable | head -1)
  [ -n "$TB" ] && { echo "-- $t:"; "$TB" || { echo RN3_UNIT_FAILED; exit 1; }; }
done
echo RN3_DONE
} > $M/logs/rn3.log 2>&1
