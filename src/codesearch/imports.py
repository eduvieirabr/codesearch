"""Import declarations from source syntax, with a backward-compatible public view."""

from __future__ import annotations

import ast
import re
import shlex
from pathlib import Path

from .grammars import get_parser


def _record(name, path, kind, local_name, imported_name, line, dynamic=False):
    return {
        "name": name,
        "path": path,
        "kind": kind,
        "local_name": local_name,
        "imported_name": imported_name,
        "line": line,
        "dynamic": dynamic,
    }


def extract_imports(path: Path, language: str) -> list[dict]:
    """Return exactly the legacy name/path/kind keys."""
    return [
        {key: record[key] for key in ("name", "path", "kind")}
        for record in extract_import_details(path, language)
    ]


def extract_import_details(path: Path, language: str) -> list[dict]:
    """Return source observations, including aliases and unresolved dynamic imports."""
    source = path.read_bytes()
    if language == "python":
        return _python(source)
    if language in {"typescript", "javascript"}:
        grammar = "tsx" if path.suffix == ".tsx" else language
        return _js_ts(source, grammar)
    if language == "bash":
        return _bash(source)
    if language in {"go", "java"}:
        return _java_go(source, language)
    return []


def _python(source: bytes) -> list[dict]:
    tree = ast.parse(source)
    results = []
    # ast.walk is breadth-first; sort afterward to preserve source order.
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                results.append(
                    _record(
                        alias.name,
                        alias.name,
                        "module",
                        alias.asname or alias.name.split(".")[0],
                        alias.name,
                        node.lineno,
                    )
                )
        elif isinstance(node, ast.ImportFrom):
            module = "." * node.level + (node.module or "")
            for alias in node.names:
                results.append(
                    _record(
                        alias.name,
                        module,
                        "from",
                        alias.asname or alias.name,
                        alias.name,
                        node.lineno,
                    )
                )
    return sorted(results, key=lambda record: record["line"])


def _walk(node):
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.named_children))


def _text(source, node):
    return source[node.start_byte : node.end_byte].decode("utf-8") if node else ""


def _literal(source, node):
    if node is None or node.type not in {
        "string",
        "raw_string",
        "interpreted_string_literal",
        "raw_string_literal",
    }:
        return None
    raw = _text(source, node)
    if raw.startswith("`"):
        return raw[1:-1]
    try:
        result = ast.literal_eval(raw)
        return result if isinstance(result, str) else None
    except (SyntaxError, ValueError):
        return None


def _js_ts(source: bytes, grammar: str) -> list[dict]:
    tree = get_parser(grammar).parse(source)
    results = []
    for node in _walk(tree.root_node):
        line = node.start_point.row + 1
        if node.type in {"import_statement", "export_statement"}:
            require_clause = next(
                (child for child in node.named_children if child.type == "import_require_clause"),
                None,
            )
            if require_clause:
                module = _literal(source, require_clause.child_by_field_name("source"))
                local = _text(source, require_clause.named_children[0])
                if module is not None:
                    results.append(_record(local, module, "require", local, "*", line))
                continue
            path_node = node.child_by_field_name("source")
            module = _literal(source, path_node)
            if module is None:
                continue  # An export without 'from' is not an import.
            clause = next(
                (
                    child
                    for child in node.named_children
                    if child.type in {"import_clause", "export_clause"}
                ),
                None,
            )
            kind = "reexport" if node.type == "export_statement" else "module"
            if clause is None:
                namespace = next(
                    (c for c in node.named_children if c.type == "namespace_export"), None
                )
                local = (
                    _text(source, namespace.named_children[-1])
                    if namespace and namespace.named_children
                    else ""
                )
                imported = "*" if kind == "reexport" else ""
                results.append(
                    _record(local or module.rsplit("/", 1)[-1], module, kind, local, imported, line)
                )
                continue
            has_default = any(child.type == "identifier" for child in clause.named_children)
            for child in clause.named_children:
                if child.type == "identifier":
                    local = _text(source, child)
                    results.append(_record(local, module, kind, local, "default", line))
                elif child.type == "namespace_import":
                    local = _text(source, child.named_children[-1])
                    results.append(_record(local, module, kind, local, "*", line))
            for specifier in _walk(clause):
                if specifier.type not in {"import_specifier", "export_specifier"}:
                    continue
                imported = _text(source, specifier.child_by_field_name("name")).strip("\"'")
                local = _text(source, specifier.child_by_field_name("alias")) or imported
                # Preserve the prior named-only versus combined-import legacy names.
                legacy = local if has_default else imported
                results.append(
                    _record(legacy, module, kind, local, imported, specifier.start_point.row + 1)
                )
        elif node.type == "call_expression":
            function = _text(source, node.child_by_field_name("function"))
            if function not in {"require", "import"}:
                continue
            arguments = node.child_by_field_name("arguments")
            if not arguments or not arguments.named_children:
                continue
            argument = arguments.named_children[0]
            literal = _literal(source, argument)
            module = literal if literal is not None else _text(source, argument)
            dynamic = function == "import" or literal is None
            kind = "dynamic" if function == "import" else "require"
            variable = node.parent
            binding = (
                variable.child_by_field_name("name")
                if variable and variable.type == "variable_declarator"
                else None
            )
            legacy = module.rsplit("/", 1)[-1]
            if binding and binding.type == "object_pattern":
                for field in binding.named_children:
                    if field.type == "pair_pattern":
                        imported = _text(source, field.child_by_field_name("key")).strip("\"'")
                        local = _text(source, field.child_by_field_name("value"))
                    elif field.type == "shorthand_property_identifier_pattern":
                        imported = local = _text(source, field)
                    else:
                        continue
                    results.append(_record(legacy, module, kind, local, imported, line, dynamic))
            else:
                local = _text(source, binding)
                results.append(_record(legacy, module, kind, local, "*", line, dynamic))
    return results


def _bash(source: bytes) -> list[dict]:
    tree = get_parser("bash").parse(source)
    results = []
    for node in _walk(tree.root_node):
        if node.type != "command" or _text(source, node.child_by_field_name("name")) not in {
            "source",
            ".",
        }:
            continue
        arguments = node.children_by_field_name("argument")
        if not arguments:
            continue
        argument = arguments[0]
        # '--' is an option separator for source, not a dependency path.
        if _text(source, argument) == "--" and len(arguments) > 1:
            argument = arguments[1]
        raw = _text(source, argument)
        dynamic = any(
            child.type
            in {
                "expansion",
                "simple_expansion",
                "command_substitution",
                "process_substitution",
                "arithmetic_expansion",
            }
            for child in _walk(argument)
        )
        if argument.type not in {"word", "string", "raw_string", "concatenation"}:
            dynamic = True
        for part in _walk(argument):
            part_text = _text(source, part)
            if part.type == "word" and (
                part_text.startswith("~") or re.search(r"(?<!\\)[*?\[]", part_text)
            ):
                dynamic = True
        try:
            path = "".join(shlex.split(raw, posix=True)) if not dynamic else raw.strip("\"'")
        except ValueError:
            path, dynamic = raw, True
        results.append(
            _record(
                path.rsplit("/", 1)[-1], path, "source", "", "*", node.start_point.row + 1, dynamic
            )
        )
    return results


def _java_go(source: bytes, language: str) -> list[dict]:
    tree = get_parser(language).parse(source)
    results = []
    for node in _walk(tree.root_node):
        if language == "java" and node.type == "import_declaration":
            match = re.match(r"import\s+(?:static\s+)?([\w.*]+)", _text(source, node))
            if match:
                module = match[1]
                name = module.rsplit(".", 1)[-1]
                results.append(
                    _record(name, module, "module", name, name, node.start_point.row + 1)
                )
        elif language == "go" and node.type == "import_spec":
            module = _literal(source, node.child_by_field_name("path"))
            if module is not None:
                local = _text(source, node.child_by_field_name("name")) or module.rsplit("/", 1)[-1]
                results.append(
                    _record(local, module, "module", local, "*", node.start_point.row + 1)
                )
    return results
