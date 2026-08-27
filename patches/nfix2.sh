#!/bin/bash
# nfix2.sh -- vLLM-parity scalar coercion: patch, rebuild, unit-test, live-probe, restore.
R=/mnt/c/Users/StevenPC/Downloads/qwen38
OUT=$R/logs/nfix2.log
PY=/opt/qwen38/venv/bin/python
AK=$(cat $R/api-key.txt)
b(){ echo; echo "########## $1 ##########"; date; }
{
b "1 PATCH"
python3 $R/nfix2_patch.py || { echo NFIX2_ABORT_PATCH; exit 1; }

b "2 REBUILD"
cmake --build /opt/ninfer/src/build -j 2>&1 | tail -6 || { echo NFIX2_ABORT_BUILD; exit 1; }

b "3 UNIT TESTS"
TB=$(find /opt/ninfer/src/build -name "*tool_call*test*" -type f -executable | head -1)
echo "test binary: $TB"
"$TB" || { echo NFIX2_ABORT_UNIT; exit 1; }

b "4 LOCAL COMMIT"
git -C /opt/ninfer/src add -A
git -C /opt/ninfer/src -c user.name=steven5210 -c user.email=shuynh5210@msn.com commit -m "serve: coerce scalar tool arguments to declared types like vLLM qwen3coder" 2>&1 | tail -2
git -C /opt/ninfer/src log --oneline -2

b "5 LIVE PROBES on patched build (106496 int8 conc2 MTP3)"
for i in $(seq 1 24); do
  RUN=$(curl -s -m 3 http://127.0.0.1:8000/metrics -H "Authorization: Bearer $AK" | grep -a "^vllm:num_requests_running" | awk '{s+=$2} END{print int(s)}')
  [ "${RUN:-0}" = "0" ] && break; sleep 10
done
bash $R/killall-vllm.sh >/dev/null 2>&1; sleep 8
nohup /opt/ninfer/src/build/apps/ninfer-serve /opt/ninfer/models/qwen3_8_27b_nvfp4.ninfer \
  --api-key "$AK" --max-context 106496 --kv-dtype int8 --max-concurrency 2 \
  --spec mtp --draft-tokens 3 --lm-head-draft > /opt/ninfer/logs/nfix2.out 2> /opt/ninfer/logs/nfix2.err &
for i in $(seq 1 40); do sleep 3; curl -s -m 3 -o /dev/null -H "Authorization: Bearer $AK" http://127.0.0.1:8080/v1/models && break; done

b "5a TOOLAB 20-call matrix (was 20/20 after fix v1)"
cd $R && TARGET_URL=http://127.0.0.1:8080/v1/chat/completions $PY -u toolab.py 2>&1 | tail -12

b "5b BOOLEAN COERCION x6 (the probe that failed 3/4 before)"
$PY - <<'PYX'
import json,time,urllib.request
AK=open('/mnt/c/Users/StevenPC/Downloads/qwen38/api-key.txt').read().strip()
TOOLS=[{"type":"function","function":{"name":"shard_rebalance","description":"Rebalance shards across replicas.",
  "parameters":{"type":"object","properties":{"shard_id":{"type":"string"},
  "target_replicas":{"type":"integer"},"drain_first":{"type":"boolean"}},
  "required":["shard_id","target_replicas"]}}}]
ok=0
for i in range(6):
    body=dict(model="qwen3.8-27b",max_tokens=800,temperature=1.0,reasoning_effort="medium",
        tools=TOOLS,tool_choice="auto",
        messages=[{"role":"user","content":"[sample %d] Rebalance shard 'shard-77' to exactly 7 target replicas and drain first. Call the tool."%i}])
    req=urllib.request.Request("http://127.0.0.1:8080/v1/chat/completions",data=json.dumps(body).encode(),
        headers={"Content-Type":"application/json","Authorization":"Bearer "+AK})
    r=json.load(urllib.request.urlopen(req,timeout=300))
    calls=r["choices"][0]["message"].get("tool_calls") or []
    if len(calls)==1:
        a=json.loads(calls[0]["function"]["arguments"])
        good=(a.get("shard_id")=="shard-77" and a.get("target_replicas")==7 and a.get("drain_first") is True)
        ok+=good
        print("sample %d: %s %s"%(i,"PASS" if good else "FAIL",json.dumps(a)))
    else:
        print("sample %d: FAIL calls=%d"%(i,len(calls)))
print("BOOLEAN %d/6"%ok)
PYX

b "6 RESTORE PRODUCTION vLLM"
pkill -9 -f ninfer-serve; sleep 8
nohup bash $R/serve-wsl.sh >/dev/null 2>&1 &
for i in $(seq 1 90); do sleep 5; curl -s -m 3 -o /dev/null http://127.0.0.1:8000/health && break; done
sleep 12
head -c 18000000 $R/logs/serve.log | tr -d '\r' | grep -aoE "GPU KV cache size: [0-9,]+" | tail -1
echo "health=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health)"
echo NFIX2_DONE
} > $OUT 2>&1
