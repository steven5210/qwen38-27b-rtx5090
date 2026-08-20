#!/usr/bin/env python3
"""Add the schema-typing unit test + docs paragraph."""
import sys
T='/opt/ninfer/src/tests/test_tool_call_parser.cpp'
t=open(T).read()
if 'test_schema_typed_parameters' in t:
    print("test already added"); sys.exit(0)
NEW_TEST=r'''
int test_schema_typed_parameters() {
    ninfer::serve::ToolParameterTypes types;
    types["write_file"] = {{"path", "string"}, {"content", "string"}, {"retries", "integer"}};
    types["configure"]  = {{"payload", "object"}};

    const ninfer::serve::ParsedToolCallOutput parsed = ninfer::serve::parse_qwen_tool_call_output(
        "<tool_call>\n"
        "<function=write_file>\n"
        "<parameter=path>\nconfig/app.json\n</parameter>\n"
        "<parameter=content>\n{\"name\": \"demo\", \"retries\": 3}\n</parameter>\n"
        "<parameter=retries>\n2\n</parameter>\n"
        "</function>\n"
        "</tool_call>\n"
        "<tool_call>\n"
        "<function=configure>\n"
        "<parameter=payload>\n{\"ok\": true}\n</parameter>\n"
        "<parameter=extra>\n7\n</parameter>\n"
        "</function>\n"
        "</tool_call>",
        64, &types);

    int failures = 0;
    failures += check(parsed.is_tool_call_response, "schema-typed calls parsed");
    failures += check(parsed.tool_calls.size() == 2, "schema-typed call count");
    const Json write_args = Json::parse(parsed.tool_calls[0].arguments_json);
    failures += check(write_args.at("content").is_string(),
                      "string-declared parameter stays a string for JSON-shaped content");
    failures += check(Json::parse(write_args.at("content").get<std::string>()).at("retries") == 3,
                      "string-declared content preserves the JSON document text");
    failures += check(write_args.at("path") == "config/app.json",
                      "string-declared plain value unchanged");
    failures += check(write_args.at("retries") == 2, "integer-declared parameter typed");
    const Json configure_args = Json::parse(parsed.tool_calls[1].arguments_json);
    failures += check(configure_args.at("payload").at("ok") == true,
                      "object-declared parameter parsed as object");
    failures += check(configure_args.at("extra") == 7,
                      "undeclared parameter keeps value inference");
    return failures;
}

int test_extract_tool_parameter_types() {
    std::vector<ninfer::serve::ToolDefinition> tools(1);
    tools[0].name            = "write_file";
    tools[0].parameters_json = R"({"type":"object","properties":{"path":{"type":"string"},"count":{"type":"integer"},"odd":{"type":123}}})";
    const ninfer::serve::ToolParameterTypes types =
        ninfer::serve::extract_tool_parameter_types(tools);
    int failures = 0;
    failures += check(types.at("write_file").at("path") == "string", "extracted string type");
    failures += check(types.at("write_file").at("count") == "integer", "extracted integer type");
    failures += check(types.at("write_file").count("odd") == 0, "non-string type entry skipped");
    return failures;
}
'''
old='int test_malformed_falls_back_to_text() {'
assert old in t
t=t.replace(old, NEW_TEST.lstrip('\n')+'\n'+old, 1)
old='    failures += test_multiple_calls_and_json_values();'
assert old in t
t=t.replace(old, old+'\n    failures += test_schema_typed_parameters();\n    failures += test_extract_tool_parameter_types();',1)
if '#include <vector>' not in t:
    t=t.replace('#include <string>','#include <string>\n#include <vector>',1)
open(T,'w').write(t); print("tests added")

D='/opt/ninfer/src/docs/serving.md'
d=open(D).read()
old=('Function tools are rendered into the model prompt and generated calls are parsed into protocol\n'
     'responses. NInfer does not execute tools and does not enforce client JSON Schema through constrained\n'
     'decoding.')
assert old in d, "docs anchor"
d=d.replace(old, old+('\nParsed argument values are typed by the declared parameter schema: a parameter declared\n'
 '`"type": "string"` is always returned as a JSON string, even when the model writes JSON-shaped\n'
 'text into it (for example a JSON document passed to a file-writing tool); other declared types\n'
 'accept a JSON value of that type and otherwise fall back to the raw text; parameters without a\n'
 'declared type keep value-based inference.'),1)
open(D,'w').write(d); print("docs updated")
