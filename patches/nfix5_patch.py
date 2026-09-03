#!/usr/bin/env python3
"""nfix5_patch.py -- tool messages accept OpenAI content-part arrays (backport of upstream eda40242).

Problem (our fork, base feaf4dd, src/serve/openai_schema.cpp): a `role: tool` message is rejected
with HTTP 400 unless `content` is a plain string. Every user/assistant turn already goes through
parse_content_parts(), which accepts a string OR an array of {"type":"text",...} parts -- the
shape Qwen Code, Claude Code, and other OpenAI clients use for tool results. Upstream fixed this
on 2026-08-28 (eda40242, refactored in 5c957c60) by routing tool turns through the same parser.

Idempotent and assert-guarded: exact anchors, refuses on drift, prints "already patched" on rerun.
Usage: python3 nfix5_patch.py [/opt/ninfer/src]
"""
import sys, pathlib

ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/opt/ninfer/src")
SRC  = ROOT / "src/serve/openai_schema.cpp"
TEST = ROOT / "tests/test_openai_schema.cpp"

OLD_SRC = '''            if (!item.contains("content") || !item.at("content").is_string()) {
                bad_request("tool messages must contain string content", "messages");
            }
            turn.tool_call_id = item.at("tool_call_id").get<std::string>();
            turn.content.push_back(
                ContentPart{ContentKind::Text, item.at("content").get<std::string>(), "text"});
            out.messages.push_back(std::move(turn));
            continue;
'''
NEW_SRC = '''            if (!item.contains("content") || item.at("content").is_null()) {
                bad_request("tool messages must contain content", "messages");
            }
            turn.tool_call_id = item.at("tool_call_id").get<std::string>();
            // nfix5: OpenAI clients (Qwen Code, Claude Code, Cline) send tool results either as a
            // plain string or as a content-part array; accept both, exactly like user turns.
            parse_content_parts(item.at("content"), turn, i);
            out.messages.push_back(std::move(turn));
            continue;
'''

OLD_TEST_ANCHOR = '''    failures +=
        check(req.messages[2].content.at(0).text == R"({"temp":20})", "tool content parsed");
'''
NEW_TEST = OLD_TEST_ANCHOR + '''
    // nfix5: tool results may arrive as a content-part array (Qwen Code / Claude Code shape).
    Json parts_body = body;
    parts_body["messages"][2]["content"] =
        Json::array({Json{{"type", "text"}, {"text", "part one"}},
                     Json{{"type", "text"}, {"text", "part two"}}});
    const GenerationRequest parts_req = parse_chat_completion_request(parts_body, default_limits());
    failures += check(parts_req.messages[2].role == ninfer::ChatRole::Tool,
                      "tool role parsed from content-part array");
    failures += check(parts_req.messages[2].content.size() == 2,
                      "tool content-part array keeps both parts");
    failures += check(parts_req.messages[2].content.at(1).text == "part two",
                      "tool content-part text preserved");
    Json empty_parts = body;
    empty_parts["messages"][2]["content"] = Json::array();
    failures += check(throws_api([&] { parse_chat_completion_request(empty_parts, default_limits()); }),
                      "empty tool content-part array rejected");
'''

def patch(path, old, new, what):
    text = path.read_text()
    if new in text:
        print("%s: already patched" % what); return
    assert text.count(old) == 1, "%s: anchor drifted (found %d) -- refusing to patch" % (what, text.count(old))
    path.write_text(text.replace(old, new, 1)); print("%s: patched" % what)

def main():
    for p in (SRC, TEST): assert p.exists(), "missing %s" % p
    patch(SRC, OLD_SRC, NEW_SRC, "openai_schema.cpp (tool content parts)")
    assert "bool throws_api(" in TEST.read_text(), "test helper throws_api not found -- check test file"
    patch(TEST, OLD_TEST_ANCHOR, NEW_TEST, "test_openai_schema.cpp (tool content-part test)")
    print("NFIX5_PATCH_OK")

if __name__ == "__main__":
    main()
