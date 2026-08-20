Title: Tool-call arguments violate the declared parameter schema when a string
parameter contains JSON-shaped text

## Summary

`parse_qwen_tool_call_output` types every `<parameter=...>` value by sniffing:
any raw text that parses as JSON becomes that JSON value
(`src/serve/tool_call_parser.cpp`, `parse_parameter`):

    Json parsed = Json::parse(raw_value, nullptr, false);
    args[key]   = parsed.is_discarded() ? Json(raw_value) : parsed;

The request's tool definitions are never consulted. When a parameter declared
`"type": "string"` receives JSON-shaped text — the everyday case of an agent
writing a JSON document through a `write_file`-style tool — the emitted
`function.arguments` contains `"content": { ... }` where the declared schema
says `"content": "..."`. Clients that trust the declared schema (Cline and
similar agents write `arguments.content` to disk as a string) break. The same
sniffing also promotes a string-declared `"123"` to a number and `"true"` to a
boolean.

## Reproduction (RTX 5090, Qwen3.8-27B NVFP4 artifact, current master)

20 `write_file` calls across five content shapes, `reasoning_effort: medium`,
OpenAI Chat Completions with the schema below:

    {"type":"function","function":{"name":"write_file","parameters":{"type":"object",
      "properties":{"path":{"type":"string"},"content":{"type":"string"}},
      "required":["path","content"]}}}

| content shape | stock master | vLLM 0.27.1, same checkpoint |
|---|---|---|
| JSON document | 0/4 | 4/4 |
| JSON w/ newline-bearing strings | 0/4 | 4/4 |
| Python module | 4/4 | 4/4 |
| shell script | 4/4 | 4/4 |
| markdown | 4/4 | 4/4 |

Every failure is `arguments.content` arriving as a JSON object. The calls are
otherwise perfect — name, structure, `finish=tool_calls` — so the model is not
at fault; the wire shape is.

## Proposed fix (implemented and validated; PR ready on request)

Type parsed values by the declared parameter schema instead of by the value:

- extract `properties.{name}.type` from each tool's `parameters_json` at
  request preparation;
- in `parse_parameter`, when a declared type exists: parse the raw text and
  accept the value only when its JSON type matches the declaration, otherwise
  keep the raw text. A string-declared parameter therefore always arrives as a
  string (a JSON *string* value still unquotes as before);
- parameters without a declared type keep today's value-based inference, so
  schema-less parsing (tool-history replay, existing unit tests) is unchanged.

Validation on this machine: all existing `ninfer_tool_call_parser_test` cases
pass unchanged, two new unit tests cover the declared-schema paths, and the
20-call matrix above goes to 20/20 on the patched build with the same
checkpoint and settings.

Happy to open the PR from `fix/schema-typed-tool-arguments` (+77/-9 across
`src/serve/tool_call_parser.{h,cpp}`, `generation_service.{h,cpp}`, tests, and
a `serving.md` contract note) — raising the issue first per CONTRIBUTING's
discuss-before-protocol-change rule.
