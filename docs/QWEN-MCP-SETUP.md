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
   - `qwen_mcp.py` (`mcp/` in this repo — or let `mcp/mac-setup.sh` do steps 1-2 for you:
     it downloads the file, merges the Claude config with a backup, and checks the tailnet)
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

   > I have a local Qwen3.8-27B available through the qwen-local MCP tools, plus Sonnet and
   > Opus subagents where the session supports them. YOU (Fable) ARE THE ORCHESTRATOR; the
   > other models are your delegates. QUALITY ALWAYS BEATS TOKEN SAVINGS -- the goal is
   > eliminating unnecessary expensive-token spend, never accepting worse output.
   >
   > QWEN OPERATING PARAMETERS (fixed -- do not deviate): server window 262,144 tokens.
   > Every qwen_submit runs at reasoning_effort xhigh with max_tokens 131,072 (thinking and
   > answer share it) -- never lower the effort or output budget. That leaves exactly
   > 131,072 tokens of prompt budget for task + context + system; size specs to fit
   > (qwen_submit pre-checks and rejects oversized). qwen_ask (effort none/low) is the only
   > sub-xhigh lane. Use qwen_status with wait:true instead of polling (chain sub-50s
   > waits for long jobs) and context_path for large file contexts.
   >
   > ROUTING -- for each subtask pick the CHEAPEST tier that delivers FULL quality (the
   > bar is identical at every tier; when in doubt between tiers, route UP):
   > 1. QWEN (free, xhigh-deep, 262K window, NO hands -- it returns text only): specified
   >    implementation, tests, and reviews against verifiable specs with cheap gates;
   >    bulk summarization. First choice whenever it qualifies. Benchmarked on a real
   >    merged PR: ~1M free local tokens replaced 2-3.5M expensive ones at equal
   >    post-review quality, zero takeovers.
   > 2. SONNET subagent (cheap, agentic hands, runs in parallel while the GPU is busy):
   >    mechanical application of payloads/diffs, file operations, running gates, and
   >    work beyond Qwen that is not judgment-heavy.
   > 3. OPUS subagent (bounded judgment): module-level design or debugging, deep review
   >    assists -- judgment work that still does not need you.
   > 4. FABLE (you): cross-cutting judgment, spec-writing, adjudication, final review --
   >    and any task where you are simply the best fit; route down only when a lower
   >    tier truly delivers full quality. Where subagents are unavailable (plain chats),
   >    the ladder collapses to Qwen <-> you.
   >
   > ESCALATION: a failure is diagnosed before it is escalated. Most delegate failures
   > are spec/context gaps -- fix the input and retry the SAME tier. A true capability
   > miss escalates to the tier the diagnosis indicates (skip tiers when the failure
   > class says so), carrying the spec plus the failure evidence. After two failed tiers
   > on one subtask, you take it over. Record every routing choice, escalation, and
   > whether results needed fixes -- calibration continues.
   >
   > NON-NEGOTIABLES at every tier: fully self-contained specs (delegates share none of
   > your context; failures usually trace to what you left out). Verify anchors, types,
   > and interfaces before applying returned code. Where a reference implementation or
   > ground truth exists, build a test probe against it IN THE PLAN, not the epilogue.
   > After ANY code change, whoever authored it, run the usual adversarial review and
   > /code-review flow. No tier self-certifies -- not Qwen, not Opus: you check the
   > output and own every verdict. If I ask you to delegate something you judge
   > unsuitable, push back with your reason and let me decide.

## The tools

| tool | what | latency |
|---|---|---|
| qwen_health | up/down, model, window, running jobs | instant |
| qwen_ask | sync question, effort none/low, <=4K out | seconds |
| qwen_submit | background job, default **effort xhigh, max_tokens 131,072**; `context_path` reads a local file (<=2MB) so huge contexts never go through tool parameters | returns instantly |
| qwen_status | snapshot -- or `wait:true` BLOCKS until done/error (default 45s, hard-clamped 50s; CHAIN calls for multi-minute jobs; clean still-running at the clamp; wakes ~instantly on completion; other tools not blocked) | instant / blocking |
| qwen_result | answer + usage (incl. cached_tokens); thinking omitted | instant |

## Timeouts and other gotchas (designed around)

- **Why waits are clamped to 50s (v1.2)**: the MCP harness KILLS the whole server process
  when a tool call blocks past ~60s -- that kill, not the wait, wiped the v1.1 job registry
  and lost a running job. v1.2 hard-clamps every wait below the threshold and persists the
  registry to <dir>/jobs/: finished results survive restarts, and a job in flight during a
  kill returns clearly marked "lost:" instead of unknown. Chain wait calls for long jobs.
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
