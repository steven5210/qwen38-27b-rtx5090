#!/bin/bash
# Stop the vLLM server + its engine cores -- and ONLY them.
#
# v2 (2026-09-01): kills by identity, never by "any venv python". v1's third pattern
# ('/opt/qwen38/venv/bin/python') killed every process using the venv -- including the 2:30
# job -- from STOP-ALL and from START-NINFER (which calls this). Now:
#   roots      = processes whose command line IS the vLLM launcher (anchored at the start)
#   members    = each root + those descendants that are venv python or a renamed VLLM:: core
#   orphans    = processes whose argv[0] is VLLM:: (engine cores that lost their parent)
#   never      = this script, its parent, or any ancestor of it
#
#   bash killall-vllm.sh            kill + wait for VRAM release
#   bash killall-vllm.sh --dry-run  print exactly what WOULD be killed, kill nothing
DRY=0; [ "$1" = "--dry-run" ] && DRY=1

VENV=/opt/qwen38/venv/bin
cmdline_of() { tr '\0' ' ' < "/proc/$1/cmdline" 2>/dev/null; }
descendants() { local c; for c in $(pgrep -P "$1" 2>/dev/null); do descendants "$c"; echo "$c"; done; }
protect=" $$ "
p=$$; while [ "$p" -gt 1 ] 2>/dev/null; do p=$(awk '{print $4}' "/proc/$p/stat" 2>/dev/null) || break; protect="$protect$p "; done
is_protected() { case "$protect" in *" $1 "*) return 0;; esac; return 1; }
is_vllm_member() {  # $1 = pid -> 0 if this process is part of the vLLM stack by identity
  local c; c=$(cmdline_of "$1")
  case "$c" in
    "$VENV/python"*|"$VENV/vllm"*|VLLM::*) return 0;;
  esac
  return 1
}

targets=""
for root in $(pgrep -f "^($VENV/python[0-9.]* )?$VENV/vllm( |\$)" 2>/dev/null); do
  for pid in $(descendants "$root") "$root"; do is_vllm_member "$pid" && targets="$targets $pid"; done
done
for pid in $(pgrep -f '^VLLM::' 2>/dev/null); do targets="$targets $pid"; done

killed=0
for pid in $(echo $targets | tr ' ' '\n' | sort -un); do
  is_protected "$pid" && continue
  c=$(cmdline_of "$pid" | cut -c1-110); [ -z "$c" ] && continue
  if [ "$DRY" = 1 ]; then echo "would kill $pid: $c"; continue; fi
  kill -9 "$pid" 2>/dev/null && killed=$((killed+1))
done
if [ "$DRY" = 1 ]; then echo "dry-run: nothing killed"; exit 0; fi

echo "killed=$killed"
sleep 4
LEFT=$(pgrep -cf "^VLLM::|^($VENV/python[0-9.]* )?$VENV/vllm( |\$)" 2>/dev/null); echo "procs_left=${LEFT:-0}"
if [ "$killed" = 0 ] && [ "${LEFT:-0}" = 0 ]; then echo "no vLLM was running; skipping VRAM wait"; exit 0; fi
for i in $(seq 1 24); do
  USED=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' ')
  if [ "${USED:-99999}" -lt 3000 ]; then echo "gpu_released=${USED}MiB"; break; fi
  sleep 5
done
exit 0
