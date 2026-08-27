#!/usr/bin/env python3
"""NFIX3: mirror the Responses API's cached_tokens telemetry into Chat Completions usage
(usage.prompt_tokens_details.cached_tokens), fed by the same prefix_cache_hit_tokens counter
that already drives the cache= completion-log line."""
import sys
B = "/opt/ninfer/src/"
def patch(path, pairs, must_have=None, skip_if=None):
    s = open(B+path).read()
    if skip_if and skip_if in s:
        print(path, "already patched; skipping"); return
    for old, new, count in pairs:
        n = s.count(old)
        assert n == count, "anchor x%d (want %d) in %s: %r" % (n, count, path, old[:70])
        s = s.replace(old, new)
    open(B+path, "w").write(s)
    print(path, "patched")

patch("src/serve/request.h", [(
"""struct CompletionUsage {
    int prompt_tokens     = 0;
    int completion_tokens = 0;
};""",
"""struct CompletionUsage {
    int prompt_tokens        = 0;
    int completion_tokens    = 0;
    int cached_prompt_tokens = 0;  // prompt tokens served from prefix reuse (0 when unknown)
};""", 1)], skip_if="cached_prompt_tokens")

patch("src/serve/http_server.cpp", [
("#include <atomic>", "#include <algorithm>\n#include <atomic>", 1),
("""            const CompletionUsage usage{outcome.prompt_tokens, outcome.completion_tokens};
            std::string response_body;""",
"""            CompletionUsage usage{outcome.prompt_tokens, outcome.completion_tokens};
            usage.cached_prompt_tokens =
                std::clamp(static_cast<int>(outcome.metrics.prefix_cache_hit_tokens), 0,
                           outcome.prompt_tokens);
            std::string response_body;""", 1),
("""                    const CompletionUsage usage{outcome.prompt_tokens, outcome.completion_tokens};
                    write_stream_item(sink, *stream,
                                      make_chat_chunk_usage(id, model, created, usage));""",
"""                    CompletionUsage usage{outcome.prompt_tokens, outcome.completion_tokens};
                    usage.cached_prompt_tokens =
                        std::clamp(static_cast<int>(outcome.metrics.prefix_cache_hit_tokens), 0,
                                   outcome.prompt_tokens);
                    write_stream_item(sink, *stream,
                                      make_chat_chunk_usage(id, model, created, usage));""", 1),
], skip_if="cached_prompt_tokens")

patch("src/serve/openai_schema.cpp", [
("""        {"usage", Json{{"prompt_tokens", usage.prompt_tokens},
                       {"completion_tokens", usage.completion_tokens},
                       {"total_tokens", usage.prompt_tokens + usage.completion_tokens}}}};""",
"""        {"usage",
         Json{{"prompt_tokens", usage.prompt_tokens},
              {"prompt_tokens_details", Json{{"cached_tokens", usage.cached_prompt_tokens}}},
              {"completion_tokens", usage.completion_tokens},
              {"total_tokens", usage.prompt_tokens + usage.completion_tokens}}}};""", 2),
("""    payload["usage"]   = Json{{"prompt_tokens", usage.prompt_tokens},
                              {"completion_tokens", usage.completion_tokens},
                              {"total_tokens", usage.prompt_tokens + usage.completion_tokens}};""",
"""    payload["usage"] =
        Json{{"prompt_tokens", usage.prompt_tokens},
             {"prompt_tokens_details", Json{{"cached_tokens", usage.cached_prompt_tokens}}},
             {"completion_tokens", usage.completion_tokens},
             {"total_tokens", usage.prompt_tokens + usage.completion_tokens}};""", 1),
], skip_if="prompt_tokens_details")

patch("tests/test_openai_schema.cpp", [
("    const CompletionUsage usage{10, 3};",
"""    CompletionUsage usage{10, 3};
    usage.cached_prompt_tokens = 4;""", 1),
('    failures += check(j.at("usage").at("total_tokens") == 13, "usage total_tokens");',
"""    failures += check(j.at("usage").at("total_tokens") == 13, "usage total_tokens");
    failures += check(j.at("usage").at("prompt_tokens_details").at("cached_tokens") == 4,
                      "usage cached_tokens mirrored from prefix reuse");""", 1),
("    const CompletionUsage usage{2, 5};",
"""    CompletionUsage usage{2, 5};
    usage.cached_prompt_tokens = 2;""", 1),
('    failures += check(usage_chunk.at("usage").at("total_tokens") == 7, "usage chunk total");',
"""    failures += check(usage_chunk.at("usage").at("total_tokens") == 7, "usage chunk total");
    failures +=
        check(usage_chunk.at("usage").at("prompt_tokens_details").at("cached_tokens") == 2,
              "usage chunk cached_tokens");""", 1),
], skip_if="cached_prompt_tokens")

patch("docs/serving.md", [
("`choices` chunk contains completed usage.",
"""`choices` chunk contains completed usage. Chat Completions usage objects also carry
`prompt_tokens_details.cached_tokens` — the resident prompt prefix reused by Engine for the
request (0 when nothing was reused), mirroring the Responses API's `input_tokens_details`.""", 1),
], skip_if="prompt_tokens_details.cached_tokens")

print("NFIX3_PATCH_OK")
