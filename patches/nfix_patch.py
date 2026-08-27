#!/usr/bin/env python3
"""Schema-typed tool arguments patch for ninfer. Idempotent, assert-guarded."""
import re, sys
H='/opt/ninfer/src/src/serve/tool_call_parser.h'
C='/opt/ninfer/src/src/serve/tool_call_parser.cpp'
h=open(H).read(); c=open(C).read()
if 'ToolParameterTypes' in h:
    print("already patched"); sys.exit(0)

old='#include <cstddef>\n#include <string>\n#include <string_view>\n#include <vector>'
assert old in h, "header includes"
h=h.replace(old,'#include <cstddef>\n#include <map>\n#include <string>\n#include <string_view>\n#include <vector>')
old=('ParsedToolCallOutput parse_qwen_tool_call_output(const std::string& text,\n'
     '                                                 std::size_t max_tool_name_length);')
assert old in h, "header decl"
new=('// Declared JSON-Schema "type" for each (tool name, parameter name), extracted\n'
     '// from the request\'s tool definitions. Parameters without an entry keep\n'
     '// value-based inference.\n'
     'using ToolParameterTypes = std::map<std::string, std::map<std::string, std::string>>;\n\n'
     'ToolParameterTypes extract_tool_parameter_types(const std::vector<ToolDefinition>& tools);\n\n'
     'ParsedToolCallOutput parse_qwen_tool_call_output(const std::string& text,\n'
     '                                                 std::size_t max_tool_name_length,\n'
     '                                                 const ToolParameterTypes* parameter_types = nullptr);')
h=h.replace(old,new)

old='bool parse_parameter(std::string_view inner, std::size_t& pos, Json& args) {'
assert old in c, "parse_parameter sig"
new=('bool declared_type_matches(const std::string& declared, const Json& value) {\n'
     '    if (declared == "string") { return value.is_string(); }\n'
     '    if (declared == "object") { return value.is_object(); }\n'
     '    if (declared == "array") { return value.is_array(); }\n'
     '    if (declared == "boolean") { return value.is_boolean(); }\n'
     '    if (declared == "integer") { return value.is_number_integer(); }\n'
     '    if (declared == "number") { return value.is_number(); }\n'
     '    if (declared == "null") { return value.is_null(); }\n'
     '    return true;\n'
     '}\n\n'
     'bool parse_parameter(std::string_view inner, std::size_t& pos, Json& args,\n'
     '                     const std::map<std::string, std::string>* parameter_types) {')
c=c.replace(old,new)

old=('    const std::string raw_value = trim_ascii(inner.substr(pos, value_end - pos));\n'
     '    Json parsed                 = Json::parse(raw_value, nullptr, false);\n'
     '    args[key]                   = parsed.is_discarded() ? Json(raw_value) : parsed;')
assert old in c, "parse_parameter body"
new=('    const std::string raw_value = trim_ascii(inner.substr(pos, value_end - pos));\n'
     '    const std::string* declared = nullptr;\n'
     '    if (parameter_types != nullptr) {\n'
     '        const auto entry = parameter_types->find(key);\n'
     '        if (entry != parameter_types->end()) { declared = &entry->second; }\n'
     '    }\n'
     '    // A value is typed by the declared parameter schema. In particular a\n'
     '    // string-declared parameter must never be promoted to a JSON object or\n'
     '    // number just because its text parses as JSON, or the emitted arguments\n'
     '    // violate the tool\'s declared schema (for example a JSON document being\n'
     '    // written through a file tool).\n'
     '    Json parsed = Json::parse(raw_value, nullptr, false);\n'
     '    if (parsed.is_discarded()) {\n'
     '        args[key] = raw_value;\n'
     '    } else if (declared == nullptr || declared_type_matches(*declared, parsed)) {\n'
     '        args[key] = std::move(parsed);\n'
     '    } else {\n'
     '        args[key] = raw_value;\n'
     '    }')
c=c.replace(old,new)

old='bool parse_one_tool_call(std::string_view block, std::size_t max_name_length, ToolCall& out) {'
assert old in c, "one_tool_call sig"
c=c.replace(old,'bool parse_one_tool_call(std::string_view block, std::size_t max_name_length,\n'
               '                         const ToolParameterTypes* parameter_types, ToolCall& out) {')

old=('    const std::string_view params = block.substr(pos, function_end - pos);\n'
     '    Json args                     = Json::object();')
assert old in c, "params anchor"
new=('    const std::string_view params = block.substr(pos, function_end - pos);\n'
     '    const std::map<std::string, std::string>* tool_types = nullptr;\n'
     '    if (parameter_types != nullptr) {\n'
     '        const auto entry = parameter_types->find(name);\n'
     '        if (entry != parameter_types->end()) { tool_types = &entry->second; }\n'
     '    }\n'
     '    Json args                     = Json::object();')
c=c.replace(old,new)

old='if (!parse_parameter(params, param_pos, args)) { return false; }'
assert old in c, "param loop"
c=c.replace(old,'if (!parse_parameter(params, param_pos, args, tool_types)) { return false; }')

old=('ParsedToolCallOutput parse_qwen_tool_call_output(const std::string& text,\n'
     '                                                 std::size_t max_tool_name_length) {')
assert old in c, "public sig"
c=c.replace(old,('ParsedToolCallOutput parse_qwen_tool_call_output(const std::string& text,\n'
                 '                                                 std::size_t max_tool_name_length,\n'
                 '                                                 const ToolParameterTypes* parameter_types) {'))

old=('        if (!parse_one_tool_call(std::string_view(text).substr(inner_begin, close - inner_begin),\n'
     '                                 max_tool_name_length, call)) {')
assert old in c, "inner call site"
c=c.replace(old,('        if (!parse_one_tool_call(std::string_view(text).substr(inner_begin, close - inner_begin),\n'
                 '                                 max_tool_name_length, parameter_types, call)) {'))
print("inner call site patched")

anchor=('ParsedToolCallOutput parse_qwen_tool_call_output(const std::string& text,\n'
        '                                                 std::size_t max_tool_name_length,\n'
        '                                                 const ToolParameterTypes* parameter_types) {')
extract=('ToolParameterTypes extract_tool_parameter_types(const std::vector<ToolDefinition>& tools) {\n'
 '    ToolParameterTypes result;\n'
 '    for (const ToolDefinition& tool : tools) {\n'
 '        if (tool.name.empty() || tool.parameters_json.empty()) { continue; }\n'
 '        const Json schema = Json::parse(tool.parameters_json, nullptr, false);\n'
 '        if (schema.is_discarded() || !schema.is_object()) { continue; }\n'
 '        const auto properties = schema.find("properties");\n'
 '        if (properties == schema.end() || !properties->is_object()) { continue; }\n'
 '        std::map<std::string, std::string>& parameter_map = result[tool.name];\n'
 '        for (const auto& [parameter_name, definition] : properties->items()) {\n'
 '            if (!definition.is_object()) { continue; }\n'
 '            const auto type = definition.find("type");\n'
 '            if (type != definition.end() && type->is_string()) {\n'
 '                parameter_map[parameter_name] = type->get<std::string>();\n'
 '            }\n'
 '        }\n'
 '    }\n'
 '    return result;\n'
 '}\n\n')
c=c.replace(anchor,extract+anchor,1)
open(H,'w').write(h); open(C,'w').write(c)
print("parser patched OK")

G='/opt/ninfer/src/src/serve/generation_service.h'
g=open(G).read()
old='#include "serve/serve_options.h"'
assert old in g; g=g.replace(old,old+'\n#include "serve/tool_call_parser.h"',1)
old='    std::size_t tool_name_max_length       = 64;'
assert old in g
g=g.replace(old,old+'\n    ToolParameterTypes tool_parameter_types;')
open(G,'w').write(g); print("generation_service.h patched")

S='/opt/ninfer/src/src/serve/generation_service.cpp'
s=open(S).read()
old='    prepared.tool_name_max_length          = request.tool_name_max_length;'
assert old in s
s=s.replace(old,old+'\n    prepared.tool_parameter_types          = extract_tool_parameter_types(request.tools);')
old='parse_qwen_tool_call_output(outcome.text, prepared.tool_name_max_length);'
assert old in s
s=s.replace(old,'parse_qwen_tool_call_output(outcome.text, prepared.tool_name_max_length,\n                                        &prepared.tool_parameter_types);')
open(S,'w').write(s); print("generation_service.cpp patched")
print("ALL PATCHES APPLIED")
