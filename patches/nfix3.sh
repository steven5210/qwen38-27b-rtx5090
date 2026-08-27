#!/bin/bash
# nfix3.sh -- cached_tokens telemetry: patch, rebuild, unit-test, commit. NO server boot.
R=/mnt/c/Users/StevenPC/Downloads/qwen38
{
echo "=== NFIX3 $(date) ==="
python3 $R/nfix3_patch.py || { echo NFIX3_ABORT_PATCH; exit 1; }
cmake --build /opt/ninfer/src/build -j 2>&1 | tail -4 || { echo NFIX3_ABORT_BUILD; exit 1; }
for t in ninfer_openai_schema_test ninfer_tool_call_parser_test ninfer_anthropic_schema_test; do
  TB=$(find /opt/ninfer/src/build -name "$t" -type f -executable | head -1)
  [ -n "$TB" ] && { echo "-- $t:"; "$TB" || { echo NFIX3_ABORT_UNIT; exit 1; }; }
done
git -C /opt/ninfer/src add -A
git -C /opt/ninfer/src -c user.name=steven5210 -c user.email=shuynh5210@msn.com commit -m "serve: report prefix-reuse in chat completions usage (prompt_tokens_details.cached_tokens)" 2>&1 | tail -2
git -C /opt/ninfer/src log --oneline -3
echo NFIX3_DONE
} > $R/logs/nfix3.log 2>&1
