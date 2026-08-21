# Delegating Claude work to local Qwen3.8-27B (MCP setup)

One local MCP server (`qwen_mcp.py`) gives Claude Desktop -- chats AND Cowork sessions
(local MCP servers are proxied into Cowork automatically) -- five tools for delegating
work to the ninfer server on this machine. Validated end-to-end on 2026-08-20.

## Install (one time, ~2 minutes)

1. Open `%APPDATA%\Claude\claude_desktop_config.json` (create it if missing).
2. Add the server (merge into an existing `mcpServers` block if you have one):

    {
      "mcpServers": {
        "qwen-local": {
          "command": "wsl.exe",
          "args": ["-d", "Ubuntu-26.04", "-u", "root", "--",
                   "python3", "-u", "/mnt/c/Users/StevenPC/Downloads/qwen38/qwen_mcp.py"]
        }
      }
    }

3. Fully quit Claude Desktop (system tray -> Quit) and reopen it.
4. Check: the tools icon in a new chat should list qwen_health / qwen_ask / qwen_submit /
   qwen_status / qwen_result. Say "run qwen_health" -- expect UP + window 252,928.

Why wsl.exe: the server runs inside WSL where 127.0.0.1:8080 is guaranteed reachable
(same path every probe in this repo used). No Windows Python, no pip installs.

## Adding it on a MacBook (reaches the PC over Tailscale)

Requirements: Tailscale running on the Mac (same tailnet), the PC on with ninfer up,
and python3 present (macOS: `python3 --version`; accept the Xcode tools prompt if asked).

1. Make a folder, e.g. `~/qwen-mcp/`, containing:
   - `qwen_mcp.py` (this repo)
   - `api-key.txt` (same one line as on the PC)
2. Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

    {
      "mcpServers": {
        "qwen-local": {
          "command": "python3",
          "args": ["-u", "/Users/YOURNAME/qwen-mcp/qwen_mcp.py"],
          "env": {"QWEN_URL": "http://100.119.25.65:8080"}
        }
      }
    }

3. Fully quit Claude Desktop (Cmd+Q) and reopen. "run qwen_health" should say UP.

Same server, same jobs, from the couch. Latency adds only the tailnet round-trip.

## Daily workflow

1. START-NINFER.bat (or leave it running).
2. In Claude, just ask -- or better, add this standing instruction to your Claude
   preferences/project. It makes Claude JUDGE each task instead of pattern-matching a
   task list, with quality always ahead of token savings:

   > I have a local Qwen3.8-27B (252,928-token context, reasoning_effort xhigh) available
   > through the qwen-local MCP tools. For any task or subtask, YOU decide whether to
   > delegate to it: judge whether a strong 27B with huge context can do this at full
   > quality -- bounded, precisely specifiable, and verifiable (tests or your own review
   > can catch failures) -- rather than needing cross-cutting judgment or context only you
   > hold. QUALITY ALWAYS BEATS TOKEN SAVINGS; when in doubt, do it yourself. If you
   > delegate: write a fully self-contained spec (Qwen shares none of your context),
   > review the result critically before using it, and take over yourself after two
   > failed attempts. If I ask you to delegate something you judge unsuitable, push back
   > with your reason and let me decide. Tell me briefly what you delegated or why you
   > chose not to, and note whether delegated results needed fixes -- so the delegation
   > judgment calibrates over time. Use qwen_ask (effort none/low) for quick lookups.

## The tools

| tool | what | latency |
|---|---|---|
| qwen_health | up/down, model, window, running jobs | instant |
| qwen_ask | sync question, effort none/low, <=4K out | seconds |
| qwen_submit | background job, default **effort xhigh, max_tokens 131,072** | returns instantly |
| qwen_status | state + phase (thinking/answering) + elapsed + sizes | instant |
| qwen_result | answer + usage (incl. cached_tokens); thinking omitted | instant |

## Timeouts and other gotchas (designed around)

- **MCP ~60s client timeouts**: irrelevant here -- submit/status/result each return in
  milliseconds while the generation runs minutes on the server. Only qwen_ask waits, and
  it is capped to the fast lane (none/low, 4K out).
- **Server down**: tools return a clear message telling Claude to have you run
  START-NINFER.bat. Nothing hangs.
- **Prompt budget**: at max_tokens=131,072 the prompt may be ~121K tokens; qwen_submit
  pre-checks size and REJECTS oversized specs with the numbers instead of erroring late.
- **Jobs live in the MCP process** (in memory): quitting Claude Desktop mid-job loses the
  job (the server finishes generating; the result is just unclaimed). Fetch results
  before quitting.
- **Concurrency**: 1 delegation job at a time by default (QWEN_MCP_JOBS env to raise;
  server lanes = 2) so a live Cline session keeps its resident cache. Two big xhigh
  jobs + active Cline can evict a resident under page pressure (LRU) -> one re-prefill.
- **Effort**: xhigh default per the validated lane (thinking 15-48K+ tokens, minutes of
  wall time). Drop to medium in the submit call for faster bounded tasks.
