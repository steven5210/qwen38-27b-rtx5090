#!/bin/bash
# stop-all.sh -- stop EVERYTHING OF OURS (ninfer + vLLM + ninfer builds), restore NOTHING.
# v2 (2026-09-01): anything that is not ours survives -- the 2:30 job, other venv users, other
# compiles. v1 used `pkill -f ninja` / `-f "cicc\|nvcc\|ptxas"` (matches those words anywhere
# in any command line) and a killall-vllm that took every venv python with it.
#   bash stop-all.sh            stop
#   bash stop-all.sh --dry-run  print what would be killed, kill nothing
DRY=""; [ "$1" = "--dry-run" ] && DRY="--dry-run"
R=/mnt/c/Users/StevenPC/Downloads/qwen38

cmdline_of() { tr '\0' ' ' < "/proc/$1/cmdline" 2>/dev/null; }
descendants() { local c; for c in $(pgrep -P "$1" 2>/dev/null); do descendants "$c"; echo "$c"; done; }
protect=" $$ "
p=$$; while [ "$p" -gt 1 ] 2>/dev/null; do p=$(awk '{print $4}' "/proc/$p/stat" 2>/dev/null) || break; protect="$protect$p "; done
is_protected() { case "$protect" in *" $1 "*) return 0;; esac; return 1; }

# 1) ninfer server: exact process name only
if [ -n "$DRY" ]; then pgrep -ax ninfer-serve | sed 's/^/would kill /'; else pkill -9 -x ninfer-serve 2>/dev/null; fi

# 2) vLLM: by identity (see killall-vllm.sh)
bash $R/killall-vllm.sh $DRY 2>/dev/null

# 3) ninfer builds only:
#    - ninja / cmake whose working directory is under /opt/ninfer
#    - nvcc (exact name) compiling a /opt/ninfer source, plus its cicc/ptxas children
build=""
for pid in $(pgrep -x ninja) $(pgrep -x cmake); do
  case "$(readlink "/proc/$pid/cwd" 2>/dev/null)" in /opt/ninfer*) build="$build $(descendants "$pid") $pid";; esac
done
for pid in $(pgrep -x nvcc); do
  case "$(cmdline_of "$pid")" in *"/opt/ninfer"*) build="$build $(descendants "$pid") $pid";; esac
done
for pid in $(echo $build | tr ' ' '\n' | sort -un); do
  is_protected "$pid" && continue
  if [ -n "$DRY" ]; then echo "would kill $pid: $(cmdline_of "$pid" | cut -c1-90)"; else kill -9 "$pid" 2>/dev/null; fi
done
[ -n "$DRY" ] && { echo "dry-run complete: nothing killed"; exit 0; }

sleep 2
echo "--- survivors on 8000/8080 (should be empty):"
ss -ltn | grep -E ':(8000|8080) ' || echo "none"
echo "--- GPU:"
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader
echo "ALL STOPPED. Nothing restarted."
