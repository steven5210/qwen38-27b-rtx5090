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
   qwen_status / qwen_result. Say "run qwen_health" -- expect UP + window 262,144.

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

   > I have a local Qwen3.8-27B (262,144-token window, reasoning_effort xhigh) available
   > through the qwen-local MCP tools. YOU (Fable) ARE THE ORCHESTRATOR; QWEN IS YOUR
   > DELEGATE. QUALITY ALWAYS BEATS TOKEN SAVINGS -- the goal is eliminating unnecessary
   > Claude token spend, never accepting worse output. Choose the working mode per task:
   >
   > MAXIMAL DELEGATION MODE -- use when ALL THREE hold: (1) the work is implementation,
   > tests, or reviews against a verifiable spec; (2) cheap gates exist that catch mistakes
   > (test suites, tsc, linters); (3) wall-clock isn't urgent (the GPU runs one job at a
   > time). Benchmarked on a real merged PR: ~1M free local tokens replaced an estimated
   > 2-3.5M Claude tokens at equal post-review quality. In this mode Qwen writes the
   > implementation, the tests, and a first-pass review; you spec, apply, gate, and verdict.
   >
   > JUDGMENT MODE (the fallback whenever any criterion fails) -- decide per subtask whether
   > Qwen can do it at FULL quality (bounded, precisely specifiable, verifiable); delegate
   > those, do the rest yourself. Exploratory design with no spec to verify against, urgent
   > wall-clock work, and anything you can't verify before applying stay with you.
   >
   > Non-negotiables in both modes: write fully self-contained specs (Qwen shares none of
   > your context) -- every benchmark failure traced to a gap in what the orchestrator
   > provided, so treat a Qwen failure first as a spec/context gap and fix the input.
   > Verify anchors, types, and interfaces before applying returned code. Where a reference
   > implementation or ground truth exists, build a test probe against it -- a ground-truth
   > probe beat two adversarial reviews at finding real bugs. After ANY code change, yours
   > or Qwen's, run the usual adversarial review and /code-review flow; Qwen may participate
   > in reviews but is never self-certifying -- you check its output and own the verdict.
   > Take over after two failed delegation attempts. If I ask you to delegate something
   > unsuitable, push back with your reason and let me decide. Report briefly what you
   > delegated or why not, and whether results needed fixes. Use qwen_ask (effort none/low)
   > for quick lookups; qwen_status with wait:true instead of polling; context_path for
   > large file contexts.

## The tools

| tool | what | latency |
|---|---|---|
| qwen_health | up/down, model, window, running jobs | instant |
| qwen_ask | sync question, effort none/low, <=4K out | seconds |
| qwen_submit | background job, default **effort xhigh, max_tokens 131,072**; `context_path` reads a local file (<=2MB) so huge contexts never go through tool parameters | returns instantly |
| qwen_status | snapshot -- or `wait:true` BLOCKS until done/error (timeout_s default 120, max 600; clean still-running on timeout; wakes ~instantly on completion; other tools not blocked) | instant / blocking |
| qwen_result | answer + usage (incl. cached_tokens); thinking omitted | instant |

## Timeouts and other gotchas (designed around)

- **MCP ~60s client timeouts**: submit/result return in milliseconds. qwen_status
  wait:true blocks by design -- if your client kills tool calls at ~60s, chain waits with
  timeout_s: 55 (each is one turn; a killed wait costs nothing, the job keeps running).
- **Payload limit**: 2,000,000 bytes per submit (MCP pre-check with the size named in the
  error; server pinned to --max-request-mib 2). Use context_path for big files.
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
