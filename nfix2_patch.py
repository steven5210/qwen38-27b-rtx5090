#!/usr/bin/env python3
"""NFIX2: vLLM-qwen3coder-parity scalar coercion for declared tool parameter types.
Exact-anchor patcher for /opt/ninfer/src on branch fix/schema-typed-tool-arguments."""
import sys
CPP = "/opt/ninfer/src/src/serve/tool_call_parser.cpp"
TST = "/opt/ninfer/src/tests/test_tool_call_parser.cpp"

cpp = open(CPP).read()
if "convert_param_value" in cpp:
    print("cpp already patched; skipping")
else:
    a = "#include <cctype>\n"
    assert a in cpp, "include anchor"
    cpp = cpp.replace(a, "#include <cctype>\n#include <charconv>\n", 1)

    anchor_fn = """    if (declared == "null") { return value.is_null(); }
    return true;
}
"""
    assert anchor_fn in cpp, "declared_type_matches tail anchor"
    helpers = anchor_fn + """
std::string ascii_lower(std::string text) {
    for (char& c : text) { c = static_cast<char>(std::tolower(static_cast<unsigned char>(c))); }
    return text;
}

bool parse_full_integer(const std::string& text, long long& out) {
    const char* begin = text.data();
    const char* end   = text.data() + text.size();
    if (begin != end && *begin == '+') { ++begin; }
    if (begin == end) { return false; }
    const auto result = std::from_chars(begin, end, out);
    return result.ec == std::errc() && result.ptr == end;
}

bool parse_full_double(const std::string& text, double& out) {
    const char* begin = text.data();
    const char* end   = text.data() + text.size();
    if (begin != end && *begin == '+') { ++begin; }
    if (begin == end) { return false; }
    const auto result = std::from_chars(begin, end, out);
    return result.ec == std::errc() && result.ptr == end;
}

// Coerce a raw <parameter=...> value by its declared JSON-schema type,
// mirroring vLLM's qwen3coder `_convert_param_value` so both stacks put the
// same argument shapes on the wire:
//   - the literal "null" (any case) becomes JSON null for every declared type;
//   - string-family declarations keep the raw text verbatim, never sniffed;
//   - int*/uint* declarations parse strictly integral text, raw text on failure;
//   - number/float declarations parse numerically, integral results collapse to
//     integers, raw text on failure;
//   - boolean/bool declarations read true/1 (any case) as true, all else false;
//   - other declarations (object, array, unrecognized names) JSON-parse the
//     text and keep the value only when it matches the declaration;
//   - parameters with no declaration keep value-based inference.
Json convert_param_value(const std::string& raw_value, const std::string* declared) {
    if (declared == nullptr) {
        Json parsed = Json::parse(raw_value, nullptr, false);
        if (parsed.is_discarded()) { return Json(raw_value); }
        return parsed;
    }
    const std::string lowered_value = ascii_lower(raw_value);
    if (lowered_value == "null") { return Json(nullptr); }
    const std::string type = ascii_lower(*declared);
    if (type == "string" || type == "str" || type == "text") { return Json(raw_value); }
    if (type.rfind("int", 0) == 0 || type.rfind("uint", 0) == 0) {
        long long integer_value = 0;
        if (parse_full_integer(raw_value, integer_value)) { return Json(integer_value); }
        return Json(raw_value);
    }
    if (type == "number" || type == "float") {
        double numeric_value = 0.0;
        if (parse_full_double(raw_value, numeric_value)) {
            const long long integral = static_cast<long long>(numeric_value);
            if (static_cast<double>(integral) == numeric_value) { return Json(integral); }
            return Json(numeric_value);
        }
        return Json(raw_value);
    }
    if (type == "boolean" || type == "bool") {
        return Json(lowered_value == "true" || lowered_value == "1");
    }
    Json parsed = Json::parse(raw_value, nullptr, false);
    if (parsed.is_discarded()) { return Json(raw_value); }
    if (declared_type_matches(type, parsed)) { return parsed; }
    return Json(raw_value);
}
"""
    cpp = cpp.replace(anchor_fn, helpers, 1)

    old_typing = """    // A value is typed by the declared parameter schema. In particular a
    // string-declared parameter must never be promoted to a JSON object or
    // number just because its text parses as JSON, or the emitted arguments
    // violate the tool's declared schema (for example a JSON document being
    // written through a file tool).
    Json parsed = Json::parse(raw_value, nullptr, false);
    if (parsed.is_discarded()) {
        args[key] = raw_value;
    } else if (declared == nullptr || declared_type_matches(*declared, parsed)) {
        args[key] = std::move(parsed);
    } else {
        args[key] = raw_value;
    }
"""
    assert old_typing in cpp, "parse_parameter typing anchor"
    new_typing = """    // A value is typed by the declared parameter schema (vLLM qwen3coder
    // parity). A string-declared parameter is never promoted to a JSON object
    // or number just because its text parses as JSON, and scalar declarations
    // coerce model spellings such as `True`, `FALSE`, or `+5` instead of
    // leaking raw strings into typed slots.
    args[key] = convert_param_value(raw_value, declared);
"""
    cpp = cpp.replace(old_typing, new_typing, 1)

    old_extract = """            const auto type = definition.find("type");
            if (type != definition.end() && type->is_string()) {
                parameter_map[parameter_name] = type->get<std::string>();
            }
"""
    assert old_extract in cpp, "extractor anchor"
    new_extract = """            const auto type = definition.find("type");
            if (type == definition.end()) { continue; }
            if (type->is_string()) {
                parameter_map[parameter_name] = type->get<std::string>();
            } else if (type->is_array()) {
                // Union declarations ("type": ["string", "null"]) resolve to
                // their first non-null member, as vLLM does.
                for (const auto& member : *type) {
                    if (member.is_string() && member.get<std::string>() != "null") {
                        parameter_map[parameter_name] = member.get<std::string>();
                        break;
                    }
                }
            }
"""
    cpp = cpp.replace(old_extract, new_extract, 1)
    open(CPP, "w").write(cpp)
    print("cpp patched")

tst = open(TST).read()
if "test_scalar_coercion" in tst:
    print("tests already patched; skipping")
else:
    a1 = "int test_extract_tool_parameter_types() {"
    assert a1 in tst, "test insert anchor"
    new_test = """int test_scalar_coercion() {
    ninfer::serve::ToolParameterTypes types;
    types["shard_rebalance"] = {{"drain_first", "boolean"}, {"force", "boolean"},
                                {"target_replicas", "integer"}, {"ratio", "number"},
                                {"note", "string"}, {"maybe", "string"}};
    const ninfer::serve::ParsedToolCallOutput parsed = ninfer::serve::parse_qwen_tool_call_output(
        "<tool_call>\\n<function=shard_rebalance>\\n"
        "<parameter=drain_first>\\nTrue\\n</parameter>\\n"
        "<parameter=force>\\nFALSE\\n</parameter>\\n"
        "<parameter=target_replicas>\\n+7\\n</parameter>\\n"
        "<parameter=ratio>\\n2.5\\n</parameter>\\n"
        "<parameter=note>\\nTrue\\n</parameter>\\n"
        "<parameter=maybe>\\nNULL\\n</parameter>\\n"
        "</function>\\n</tool_call>",
        64, &types);
    int failures = 0;
    failures += check(parsed.is_tool_call_response, "coercion call parsed");
    const Json args = Json::parse(parsed.tool_calls[0].arguments_json);
    failures += check(args.at("drain_first").is_boolean() && args.at("drain_first") == true,
                      "boolean-declared True coerces to true");
    failures += check(args.at("force").is_boolean() && args.at("force") == false,
                      "boolean-declared FALSE coerces to false");
    failures += check(args.at("target_replicas") == 7, "integer-declared +7 coerces to 7");
    failures += check(args.at("ratio") == 2.5, "number-declared 2.5 stays numeric");
    failures += check(args.at("note") == "True", "string-declared True stays text");
    failures += check(args.at("maybe").is_null(), "any-case null literal maps to JSON null");
    return failures;
}

int test_extract_tool_parameter_types() {"""
    tst = tst.replace(a1, new_test, 1)

    a2 = 'tools[0].parameters_json = R"({"type":"object","properties":{"path":{"type":"string"},"count":{"type":"integer"},"odd":{"type":123}}})";'
    assert a2 in tst, "extractor test schema anchor"
    tst = tst.replace(a2, 'tools[0].parameters_json = R"({"type":"object","properties":{"path":{"type":"string"},"count":{"type":"integer"},"odd":{"type":123},"opt":{"type":["null","string"]}}})";', 1)

    a3 = '    failures += check(types.at("write_file").count("odd") == 0, "non-string type entry skipped");'
    assert a3 in tst, "extractor assert anchor"
    tst = tst.replace(a3, a3 + '\n    failures += check(types.at("write_file").at("opt") == "string", "union type resolves to first non-null member");', 1)

    a4 = "    failures += test_extract_tool_parameter_types();"
    assert a4 in tst, "main anchor"
    tst = tst.replace(a4, "    failures += test_scalar_coercion();\n" + a4, 1)
    open(TST, "w").write(tst)
    print("tests patched")
print("NFIX2_PATCH_OK")
