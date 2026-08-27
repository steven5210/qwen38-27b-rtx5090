#!/bin/bash
# mac-setup.sh -- set up the qwen-local Claude Desktop MCP on a MacBook.
# Installs to ~/qwen-mcp, merges claude_desktop_config.json (backup kept), never touches
# anything else. You add the API key yourself afterward.
set -e
RAW="https://raw.githubusercontent.com/steven5210/qwen38-27b-rtx5090/main"
QWEN_URL="${QWEN_URL:-http://100.119.25.65:8080}"

echo "== qwen-local MCP setup for macOS =="

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found. Run:  xcode-select --install   then re-run this script."
  exit 1
fi
echo "python3: $(python3 --version 2>&1)"

mkdir -p "$HOME/qwen-mcp"
echo "downloading qwen_mcp.py ..."
curl -fsSL "$RAW/mcp/qwen_mcp.py" -o "$HOME/qwen-mcp/qwen_mcp.py"

if [ ! -s "$HOME/qwen-mcp/api-key.txt" ]; then
  printf 'PASTE-YOUR-KEY-HERE' > "$HOME/qwen-mcp/api-key.txt"
  echo "created ~/qwen-mcp/api-key.txt (placeholder -- paste your real key into it)"
else
  echo "api-key.txt already present, leaving it alone"
fi

CFG_DIR="$HOME/Library/Application Support/Claude"
CFG="$CFG_DIR/claude_desktop_config.json"
mkdir -p "$CFG_DIR"
[ -f "$CFG" ] && cp "$CFG" "$CFG.bak.$(date +%s)" && echo "backed up existing config"

CFG="$CFG" QWEN_URL="$QWEN_URL" python3 - <<'PY'
import json, os
cfg_path = os.environ["CFG"]
try:
    with open(cfg_path) as f: cfg = json.load(f)
    if not isinstance(cfg, dict): cfg = {}
except Exception:
    cfg = {}
cfg.setdefault("mcpServers", {})["qwen-local"] = {
    "command": "python3",
    "args": ["-u", os.path.expanduser("~/qwen-mcp/qwen_mcp.py")],
    "env": {"QWEN_URL": os.environ["QWEN_URL"]},
}
with open(cfg_path, "w") as f: json.dump(cfg, f, indent=2)
print("config written:", cfg_path)
print("servers now configured:", ", ".join(cfg["mcpServers"]))
PY

echo
echo "checking the tailnet path to the PC ($QWEN_URL) ..."
CODE=$(curl -s -m 5 -o /dev/null -w '%{http_code}' "$QWEN_URL/v1/models" || true)
case "$CODE" in
  401|200) echo "  reachable (HTTP $CODE) -- Tailscale route to the PC works." ;;
  *)       echo "  not reachable right now (got '$CODE'). Fine for setup -- but before use:"
           echo "  Tailscale ON on this Mac, PC on, START-NINFER running." ;;
esac

echo
echo "== done. Two steps left =="
echo "1) Put the real API key in:  ~/qwen-mcp/api-key.txt   (open -e ~/qwen-mcp/api-key.txt)"
echo "   One line, no spaces or trailing newline issues -- just the key."
echo "2) Fully quit Claude Desktop (Cmd+Q) and reopen. Then say: run qwen_health"
