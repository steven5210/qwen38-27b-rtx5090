#!/usr/bin/env python3
"""Minimal ninfer monitor: READY state, VRAM, request + prefix-reuse tallies, throughput."""
import json,os,re,subprocess,time,urllib.request
R="/mnt/c/Users/StevenPC/Downloads/qwen38"
ERR="/opt/ninfer/logs/prod.err"
try: KEY=open(os.path.join(R,"api-key.txt")).read().strip()
except Exception: KEY=""
def up():
    try:
        req=urllib.request.Request("http://127.0.0.1:8080/v1/models",headers={"Authorization":"Bearer "+KEY})
        urllib.request.urlopen(req,timeout=3); return True
    except Exception: return False
def vram():
    try:
        o=subprocess.run(["nvidia-smi","--query-gpu=memory.used,memory.total","--format=csv,noheader,nounits"],
                         capture_output=True,text=True,timeout=5).stdout.strip().split(",")
        return int(o[0]),int(o[1])
    except Exception: return -1,-1
while True:
    os.system("clear")
    print("=== NINFER MONITOR  (Qwen3.8-27B NVFP4, :8080) ===")
    print(time.strftime("%H:%M:%S"))
    alive=up()
    print("\n  STATUS: " + ("READY -- serving on http://127.0.0.1:8080/v1" if alive else "booting / down"))
    u,t=vram()
    if u>0:
        free=t-u
        warn="" if free>2100 else ("  << CAUTION low free VRAM" if free>1500 else "  << DANGER very low free VRAM")
        print("  VRAM  : %5d / %5d MiB  (%d free)%s"%(u,t,free,warn))
    try:
        tail=subprocess.run(["tail","-c","400000",ERR],capture_output=True,text=True,timeout=5).stdout
        cac=[int(x) for x in re.findall(r"cache=(\d+)",tail)]
        if cac:
            hits=[c for c in cac if c>0]
            print("  REQS  : %d recent   prefix-reuse on %d (%.0f%%), %s tokens reused"
                  %(len(cac),len(hits),100.0*len(hits)/len(cac),format(sum(hits),",")))
            print("  LAST 6 cache= " + " ".join(str(c) for c in cac[-6:]))
        th=re.findall(r"(prefill|decode)[^\n]*?([0-9.]+)\s*tok(?:ens)?/s",tail)
        if th:
            print("  RATES : " + "  ".join("%s %s tok/s"%(a,b) for a,b in th[-2:]))
    except Exception:
        pass
    print("\n  (ctrl-c or close window to exit; server keeps running)")
    time.sleep(5)
