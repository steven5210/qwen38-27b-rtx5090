#!/bin/bash
AK=$(cat /mnt/c/Users/StevenPC/Downloads/qwen38/api-key.txt)
{
echo "=== CTOKPROBE $(date)"
B='{"model":"qwen3.8-27b","max_tokens":40,"temperature":1.0,"reasoning_effort":"none","messages":[{"role":"user","content":"Repeat the word ready once. Context filler: the quick brown fox jumps over the lazy dog again and again and again, module alpha bravo charlie delta echo foxtrot golf hotel india juliett kilo lima mike november oscar papa quebec romeo sierra tango uniform victor whiskey xray yankee zulu, end of filler."}]}'
for i in 1 2; do
  echo "--- request $i usage:"
  curl -s -m 60 http://127.0.0.1:8080/v1/chat/completions -H "Content-Type: application/json" -H "Authorization: Bearer $AK" -d "$B" | python3 -c "import json,sys; print(json.dumps(json.load(sys.stdin).get('usage')))"
done
echo CTOKPROBE_DONE
} > /mnt/c/Users/StevenPC/Downloads/qwen38/logs/ctokprobe.log 2>&1
