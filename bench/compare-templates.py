#!/usr/bin/env python3
"""
compare-templates.py -- official Qwen3.8 chat template vs froggeric "fixed" v22.x.

The claim worth testing (froggeric README): "Mutated past turns destroy the prefix cache",
fixed by "enforced chronological history for a 100% KV cache hit rate".

MECHANISM UNDER TEST: if a template rewrites ALREADY-SENT assistant turns as the
conversation grows (e.g. blanking their <think> content), then the rendered prefix at turn
N+1 diverges from the prefix at turn N. vLLM's prefix cache matches from the first token, so
divergence at turn 2 throws away the cache for the ENTIRE conversation, every single turn.
In a Cline agent loop that is the difference between 3.5s and 9s to first token on every step.

This is measured offline with jinja2 -- no server involved, fully deterministic, zero risk.

Metrics per template:
  stable_prefix_tokens  = longest common token prefix between render(turns[:n]) and
                          render(turns[:n+1]), for each n
  cacheable_fraction    = stable_prefix_tokens / tokens in render(turns[:n])
                          1.00 = perfect cache reuse; 0.xx = that fraction survives
  total_tokens          = rendered size (token-waste claim)
"""
import json, sys, os, argparse

sys.path.insert(0, "/opt/qwen38/venv/lib/python3.12/site-packages")
from jinja2 import Environment, BaseLoader
from jinja2.exceptions import TemplateError
from transformers import AutoTokenizer

MODEL_DIR = os.environ.get("MODEL_DIR", "unsloth/Qwen3.8-27B-NVFP4")

def make_env():
    env = Environment(loader=BaseLoader(), trim_blocks=False, lstrip_blocks=False,
                      extensions=["jinja2.ext.loopcontrols"])
    env.policies["json.dumps_kwargs"] = {"ensure_ascii": False}
    def raise_exception(msg): raise TemplateError(msg)
    env.globals["raise_exception"] = raise_exception
    env.globals["strftime_now"] = lambda fmt: "2026-08-18"
    return env

TOOLS = [{"type": "function", "function": {
    "name": "read_file",
    "description": "Read a file from the workspace.",
    "parameters": {"type": "object",
        "properties": {"path": {"type": "string"}, "start_line": {"type": "integer"}},
        "required": ["path"]}}}]

def build_conversation(n_turns=8):
    """A Cline-shaped agent loop: reasoning + tool call + tool result, repeatedly."""
    msgs = [{"role": "system", "content": "You are a coding agent working in a repository."},
            {"role": "user", "content": "Refactor the auth module to use the new token store. "
                                        "Work step by step and use tools."}]
    for i in range(n_turns):
        msgs.append({"role": "assistant",
                     "reasoning_content": ("Step %d: I need to inspect the current implementation "
                                           "before editing. Let me read the relevant file and check "
                                           "how the token store is constructed, then plan the edit "
                                           "so I do not break the existing callers." % i) * 3,
                     "content": "Reading the next file.",
                     "tool_calls": [{"id": "call_%d" % i, "type": "function",
                                     "function": {"name": "read_file",
                                                  # vLLM 0.27.1 chat_utils.py pre-parses the
                                                  # OpenAI wire string into a dict before the
                                                  # template sees it -- match that exactly.
                                                  "arguments": {"path": "src/auth/mod_%d.py" % i,
                                                                "start_line": 1}}}]})
        msgs.append({"role": "tool", "tool_call_id": "call_%d" % i,
                     "content": "def handler_%d(req):\n    return TokenStore().get(req.sid)\n" % i})
    return msgs

def render(env, src, msgs, **kw):
    tpl = env.from_string(src)
    return tpl.render(messages=msgs, tools=TOOLS, add_generation_prompt=True,
                      bos_token="", eos_token="<|im_end|>", **kw)

def common_prefix_len(a, b):
    n = min(len(a), len(b)); i = 0
    while i < n and a[i] == b[i]: i += 1
    return i

def analyse(name, src, tok, msgs):
    env = make_env()
    print("\n===== %s =====" % name)
    # render at each agent step (each step adds one assistant+tool pair)
    steps, renders = [], []
    base = 2  # system + user
    k = base
    while k <= len(msgs):
        try:
            r = render(env, src, msgs[:k])
        except Exception as e:
            print("  RENDER ERROR at %d messages: %s: %s" % (k, type(e).__name__, e))
            return None
        renders.append(tok(r)); steps.append(k); k += 2
    rows = []
    for i in range(len(renders) - 1):
        cur, nxt = renders[i], renders[i + 1]
        lcp = common_prefix_len(cur, nxt)
        frac = lcp / len(cur) if cur else 0.0
        rows.append((steps[i], len(cur), lcp, frac))
        print("  after step %-2d: rendered=%-6d stable_prefix=%-6d cacheable=%.3f"
              % (i + 1, len(cur), lcp, frac))
    worst = min(r[3] for r in rows) if rows else 0
    mean = sum(r[3] for r in rows) / len(rows) if rows else 0
    print("  --> final rendered tokens: %d" % len(renders[-1]))
    print("  --> cacheable fraction: mean=%.3f worst=%.3f" % (mean, worst))
    return dict(name=name, mean=mean, worst=worst, final_tokens=len(renders[-1]),
                rows=rows)

def probe_features(name, src, tok):
    """Behavioural checks that matter for OUR config."""
    env = make_env()
    out = {}
    base = [{"role": "user", "content": "hi"}]
    # 1. thinking disabled (official 3.8 reportedly crashes)
    for kw in ({"enable_thinking": False}, {"reasoning_effort": "medium"},
               {"reasoning_effort": "xhigh"}, {"reasoning_effort": "low"}, {}):
        label = json.dumps(kw) if kw else "(defaults)"
        try:
            r = render(env, src, base, **kw)
            out[label] = "ok len=%d" % len(tok(r))
        except Exception as e:
            out[label] = "ERROR %s: %s" % (type(e).__name__, str(e)[:70])
    # 2. what tool-call syntax does it teach the model to emit?
    r = render(env, src, base)
    syntax = []
    if "<tool_call>" in r: syntax.append("<tool_call> (qwen3_coder / qwen3 parser)")
    if "<function=" in r or "<function " in r: syntax.append("<function=...> XML (qwen3_xml parser)")
    if "<tools>" in r: syntax.append("<tools> block")
    out["_tool_syntax"] = ", ".join(syntax) or "none detected"
    print("\n----- %s: feature probe -----" % name)
    for k, v in out.items():
        print("  %-34s %s" % (k, v))
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--official", default="/opt/qwen38/chat_template_official.jinja")
    ap.add_argument("--fixed", required=True)
    ap.add_argument("--turns", type=int, default=8)
    a = ap.parse_args()

    tk = AutoTokenizer.from_pretrained(MODEL_DIR, trust_remote_code=True)
    tok = lambda s: tk.encode(s, add_special_tokens=False)
    msgs = build_conversation(a.turns)
    print("conversation: %d messages (%d agent steps)" % (len(msgs), a.turns))

    res = {}
    for name, path in (("OFFICIAL", a.official), ("FIXED (froggeric)", a.fixed)):
        if not os.path.exists(path):
            print("MISSING: %s" % path); continue
        src = open(path, encoding="utf-8").read()
        res[name] = analyse(name, src, tok, msgs)
        probe_features(name, src, tok)

    print("\n" + "=" * 70)
    o, f = res.get("OFFICIAL"), res.get("FIXED (froggeric)")
    if o and f:
        print("%-22s %-14s %-14s" % ("metric", "OFFICIAL", "FIXED"))
        print("%-22s %-14.3f %-14.3f" % ("cacheable mean", o["mean"], f["mean"]))
        print("%-22s %-14.3f %-14.3f" % ("cacheable worst", o["worst"], f["worst"]))
        print("%-22s %-14d %-14d" % ("final tokens", o["final_tokens"], f["final_tokens"]))
        print("-" * 70)
        if f["mean"] > o["mean"] + 0.02:
            print("VERDICT: FIXED preserves more prefix. Official mutates history -> cache loss.")
        elif o["mean"] > f["mean"] + 0.02:
            print("VERDICT: OFFICIAL preserves more prefix. The 'fix' is not a fix here.")
        else:
            print("VERDICT: NO MEANINGFUL DIFFERENCE in prefix stability (%.3f vs %.3f)."
                  % (o["mean"], f["mean"]))
            print("         The cache-destruction claim does not reproduce on this model.")
        d = o["final_tokens"] - f["final_tokens"]
        print("Token delta at %d steps: %+d tokens (%s)" % (
            a.turns, -d if False else d, "fixed is smaller" if d > 0 else "official is smaller"))
    print("TEMPLATECMP_DONE")

if __name__ == "__main__":
    main()
