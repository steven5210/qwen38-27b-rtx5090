import json, collections, os
P = os.environ.get("JSONL_PATH", "/opt/ninfer/logs/p2.jsonl")
recs = []
with open(P) as f:
    for line in f:
        line = line.strip()
        if not line: continue
        try: recs.append(json.loads(line))
        except Exception: pass
print("records:", len(recs))
done = [r for r in recs if r.get("event") == "request_done"] or recs
print("done-events:", len(done))
if done:
    r0 = done[0]
    print("keys:", sorted(r0.keys()))
    print("first record (1200 chars):", json.dumps(r0)[:1200])
agg = collections.Counter(); tot = collections.Counter()
for r in done:
    for k, v in r.items():
        lk = k.lower()
        if any(t in lk for t in ("cache", "reuse", "prefix", "cached")):
            if isinstance(v, (int, float)):
                tot[k] += v; agg[k] += 1
            else:
                agg[f"{k}={v}"] += 1
print("cache-ish field occurrence:", dict(agg))
print("cache-ish field sums:", dict(tot))
for cand in ("cached_tokens", "prefix_cached_tokens", "kv_reused_tokens", "reused_tokens"):
    if any(cand in r for r in done):
        c = sum(r.get(cand, 0) for r in done)
        p = sum(r.get("prompt_tokens", 0) for r in done)
        print(f"{cand}: {c} / prompt_tokens: {p} -> {100.0*c/max(p,1):.1f}% of prompt tokens reused")
print("PEEK_DONE")
