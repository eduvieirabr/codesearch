"""Source-only symbol extraction; references are syntactic, never compiler resolved."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import tomllib
from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .grammars import get_parser

PARSER_REVISION = "2-rich-symbols-3"

EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".sql": "sql",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".json": "json",
    ".java": "java",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".go": "go",
    ".md": "markdown",
    ".mdx": "markdown",
    ".rs": "rust",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".sh": "bash",
    ".bash": "bash",
    ".toml": "toml",
}


@dataclass
class SymbolInfo:
    name: str
    kind: str
    file: str
    line: int
    signature: str
    summary: str
    end_line: int = 0
    qualified_name: str = ""
    language: str = ""
    parent: str | None = None
    decorators: list[str] = field(default_factory=list)
    docstring: str = ""
    bases: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    start_byte: int = 0
    end_byte: int = 0
    source_start_line: int = 0
    symbol_id: str = ""


class _Source:
    def __init__(self, data: bytes, filepath: str, language: str):
        self.data = data
        self.text = data.decode("utf-8")
        self.filepath = filepath
        self.language = language
        self.lines = [0, *(m.end() for m in re.finditer(b"\n", data))]
        self._byte_checkpoints: list[int] | None = None

    def line(self, offset: int) -> int:
        return bisect_right(self.lines, offset)

    def byte(self, character_offset: int) -> int:
        # Bound repeated UTF-8 conversions even for a large single-line JSON document.
        if self._byte_checkpoints is None:
            self._byte_checkpoints = [0]
            for start in range(0, len(self.text), 1024):
                self._byte_checkpoints.append(
                    self._byte_checkpoints[-1]
                    + len(self.text[start : start + 1024].encode("utf-8"))
                )
        block = character_offset // 1024
        return self._byte_checkpoints[block] + len(
            self.text[block * 1024 : character_offset].encode("utf-8")
        )

    def node_text(self, node) -> str:
        return self.data[node.start_byte : node.end_byte].decode("utf-8") if node else ""

    def symbol(
        self,
        name: str,
        kind: str,
        start: int,
        end: int,
        *,
        parent=None,
        signature=None,
        line=None,
        **metadata,
    ) -> SymbolInfo:
        end = max(start, end)
        return SymbolInfo(
            name=name,
            kind=kind,
            file=self.filepath,
            line=line or self.line(start),
            end_line=self.line(max(start, end - 1)),
            signature=signature if signature is not None else name,
            summary=metadata.pop("summary", ""),
            qualified_name=f"{parent}.{name}" if parent else name,
            language=self.language,
            parent=parent,
            start_byte=start,
            end_byte=end,
            source_start_line=self.line(start),
            **metadata,
        )


def extract_symbols(path: Path, language: str, filepath: str | None = None) -> list[SymbolInfo]:
    """Extract symbols with UTF-8 byte coordinates in the supplied source snapshot."""
    source = _Source(path.read_bytes(), filepath if filepath is not None else path.name, language)
    if language == "python":
        symbols = _python(source)
    elif language in {"java", "javascript", "typescript", "go", "rust", "bash"}:
        grammar = "tsx" if language == "typescript" and path.suffix == ".tsx" else language
        root = get_parser(grammar).parse(source.data).root_node
        if root.has_error:
            # A recovered syntax tree can omit declarations; do not report it as complete.
            raise SyntaxError(f"Invalid {language} syntax in {source.filepath}")
        symbols = _syntax_symbols(source, root)
    elif language == "json":
        symbols = _json(source)
    elif language == "yaml":
        symbols = _yaml(source)
    elif language == "markdown":
        symbols = _markdown(source)
    elif language == "toml":
        symbols = _toml(source)
    elif language == "sql":
        symbols = _sql(source)
    else:
        return []
    occurrences: Counter[str] = Counter()
    for symbol in symbols:
        # Coordinates and bodies are excluded so inserting lines does not change identity.
        identity = json.dumps(
            [
                symbol.file,
                language,
                symbol.kind,
                symbol.qualified_name,
                " ".join(symbol.signature.split()),
            ],
            ensure_ascii=False,
        )
        occurrence = occurrences[identity]
        occurrences[identity] += 1
        symbol.symbol_id = (
            "sym_" + hashlib.sha256(f"{identity}\0{occurrence}".encode("utf-8")).hexdigest()[:32]
        )
    return symbols


def _python(source: _Source) -> list[SymbolInfo]:
    tree = ast.parse(source.data)
    symbols = []

    def calls(statements):
        found = []

        class Calls(ast.NodeVisitor):
            def visit_Call(self, node):
                found.append(ast.unparse(node.func))
                self.generic_visit(node)

            def visit_FunctionDef(self, node):
                pass

            visit_AsyncFunctionDef = visit_FunctionDef
            visit_ClassDef = visit_FunctionDef
            visit_Lambda = visit_FunctionDef

        visitor = Calls()
        for statement in statements:
            visitor.visit(statement)
        return list(dict.fromkeys(found))

    def walk(nodes, parent=None):
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                is_class = isinstance(node, ast.ClassDef)
                start = source.lines[node.lineno - 1] + node.col_offset
                if node.decorator_list:
                    decorator = node.decorator_list[0]
                    # A parenthesized decorator's AST expression may start below '@'.
                    for row in range(decorator.lineno - 1, -1, -1):
                        candidate = source.lines[row] + node.col_offset
                        if source.data[candidate : candidate + 1] == b"@":
                            start = candidate
                            break
                end = source.lines[node.end_lineno - 1] + node.end_col_offset
                decorators = [
                    ast.get_source_segment(source.text, d) or ast.unparse(d)
                    for d in node.decorator_list
                ]
                docstring = ast.get_docstring(node) or ""
                bases = [ast.unparse(base) for base in node.bases] if is_class else []
                if is_class:
                    signature = (
                        "class " + node.name + ("(" + ", ".join(bases) + ")" if bases else "")
                    )
                else:
                    prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
                    signature = f"{prefix}def {node.name}({ast.unparse(node.args)})"
                    if node.returns:
                        signature += " -> " + ast.unparse(node.returns)
                symbol = source.symbol(
                    node.name,
                    "class" if is_class else "function",
                    start,
                    end,
                    parent=parent,
                    signature=signature,
                    line=node.lineno,
                    decorators=decorators,
                    docstring=docstring,
                    summary=docstring.splitlines()[0] if docstring else "",
                    bases=bases,
                    calls=calls(node.body),
                )
                symbols.append(symbol)
                if is_class:
                    walk(node.body, symbol.qualified_name)
                # Functions intentionally suppress nested functions and local classes.
            else:
                walk(list(ast.iter_child_nodes(node)), parent)

    walk(tree.body)
    return symbols


_CLASS_NODES = {
    "class_declaration",
    "interface_declaration",
    "record_declaration",
    "enum_declaration",
    "annotation_type_declaration",
    "abstract_class_declaration",
    "struct_item",
    "enum_item",
    "trait_item",
}
_FUNCTION_NODES = {
    "function_declaration",
    "generator_function_declaration",
    "method_definition",
    "method_signature",
    "abstract_method_signature",
    "method_declaration",
    "constructor_declaration",
    "compact_constructor_declaration",
    "function_item",
    "function_signature_item",
    "function_definition",
}
_ANONYMOUS_FUNCTION_NODES = {
    "arrow_function",
    "function_expression",
    "generator_function",
    "lambda_expression",
    "closure_expression",
    "func_literal",
}


def _comment(node, source: _Source) -> str:
    previous = node.prev_named_sibling
    if previous is None or "comment" not in previous.type:
        return ""
    if node.start_point.row - previous.end_point.row > 1:
        return ""
    raw = source.node_text(previous)
    lines = [
        re.sub(r"^\s*(?:/\*+|\*/|//+|\*)?\s?", "", line).rstrip("*/ ") for line in raw.splitlines()
    ]
    return "\n".join(line for line in lines if line).strip()


def _bases(node, source: _Source) -> list[str]:
    containers = {
        "superclass",
        "super_interfaces",
        "extends_interfaces",
        "class_heritage",
        "extends_clause",
        "implements_clause",
        "extends_type_clause",
        "type_list",
    }
    result = []

    def add(container):
        for child in container.named_children:
            if child.type in containers:
                add(child)
            elif child.type != "type_arguments":
                result.append(source.node_text(child))

    for child in node.named_children:
        if child.type in containers:
            add(child)
    return result


def _syntax_calls(body, source: _Source) -> list[str]:
    if body is None:
        return []
    found = []
    stack = [body]
    while stack:
        node = stack.pop()
        if (
            node is not body
            and node.type in _CLASS_NODES | _FUNCTION_NODES | _ANONYMOUS_FUNCTION_NODES
        ):
            continue
        call = None
        if node.type == "call_expression":
            call = node.child_by_field_name("function")
        elif node.type == "method_invocation":
            name = source.node_text(node.child_by_field_name("name"))
            obj = source.node_text(node.child_by_field_name("object"))
            found.append(f"{obj}.{name}" if obj else name)
        elif node.type in {"object_creation_expression", "new_expression"}:
            call = node.child_by_field_name("type") or node.child_by_field_name("constructor")
        elif node.type == "explicit_constructor_invocation":
            call = node.child_by_field_name("constructor")
        elif node.type == "command":
            call = node.child_by_field_name("name")
        if call:
            found.append(source.node_text(call))
        stack.extend(reversed(node.named_children))
    return list(dict.fromkeys(found))


def _syntax_symbols(source: _Source, root) -> list[SymbolInfo]:
    symbols = []

    def visit(node, parent=None):
        name_node = node.child_by_field_name("name")
        body = node.child_by_field_name("body")
        kind = None
        if node.type in _CLASS_NODES:
            kind = "class"
        elif node.type in _FUNCTION_NODES:
            kind = "function"
        elif node.type == "type_alias_declaration":
            kind = "type"
        elif node.type == "type_spec":
            declared_type = node.child_by_field_name("type")
            if declared_type and declared_type.type in {"struct_type", "interface_type"}:
                kind, body = "class", declared_type
        elif node.type in {"variable_declarator", "public_field_definition", "field_definition"}:
            value = node.child_by_field_name("value")
            if value and value.type in _ANONYMOUS_FUNCTION_NODES:
                kind = "function"
                body = value.child_by_field_name("body")
        if kind and name_node:
            name = source.node_text(name_node)
            local_parent = parent
            if source.language == "go" and node.type == "method_declaration":
                receiver = node.child_by_field_name("receiver")
                if receiver and receiver.named_children:
                    receiver_type = receiver.named_children[0].child_by_field_name("type")
                    local_parent = source.node_text(receiver_type).lstrip("*") or parent
            signature_end = body.start_byte if body else node.end_byte
            signature = source.data[node.start_byte : signature_end].decode().strip().rstrip(";")
            extent = node.parent if node.parent and node.parent.type == "export_statement" else node
            decorator_nodes = [
                child for child in extent.named_children if child.type == "decorator"
            ]
            if extent != node:
                decorator_nodes.extend(
                    child for child in node.named_children if child.type == "decorator"
                )
            preceding = node.prev_named_sibling
            while preceding is not None and preceding.type == "decorator":
                decorator_nodes.insert(0, preceding)
                preceding = preceding.prev_named_sibling
            decorator_nodes = list({d.start_byte: d for d in decorator_nodes}.values())
            decorator_nodes.sort(key=lambda d: d.start_byte)
            start = min([extent.start_byte, *(d.start_byte for d in decorator_nodes)])
            comment_node = (
                decorator_nodes[0]
                if decorator_nodes and decorator_nodes[0].start_byte < extent.start_byte
                else extent
            )
            docstring = _comment(comment_node, source)
            decorators = [source.node_text(child).lstrip("@") for child in decorator_nodes]
            for child in node.named_children:
                if child.type == "modifiers":
                    decorators.extend(
                        source.node_text(a).lstrip("@")
                        for a in child.named_children
                        if "annotation" in a.type
                    )
            if kind == "class" and source.language == "go":
                signature = f"type {name} " + (
                    "struct" if body.type == "struct_type" else "interface"
                )
            symbol = source.symbol(
                name,
                kind,
                start,
                extent.end_byte,
                parent=local_parent,
                line=node.start_point.row + 1,
                signature=signature,
                docstring=docstring,
                summary=docstring.splitlines()[0] if docstring else "",
                decorators=decorators,
                bases=_bases(node, source),
                calls=_syntax_calls(body, source),
            )
            symbols.append(symbol)
            if kind == "class" and body:
                for child in body.named_children:
                    visit(child, symbol.qualified_name)
            return
        if node.type in _ANONYMOUS_FUNCTION_NODES:
            return
        if source.language == "rust" and node.type == "impl_item":
            impl_type = node.child_by_field_name("type")
            parent = source.node_text(impl_type) or parent
        for child in node.named_children:
            visit(child, parent)

    visit(root)
    return symbols


def _json(source: _Source) -> list[SymbolInfo]:
    document = json.loads(source.text)
    if not isinstance(document, dict):
        return []
    decoder = json.JSONDecoder()
    symbols = []

    def entries(start):
        offset = start + 1
        while True:
            while source.text[offset].isspace() or source.text[offset] == ",":
                offset += 1
            if source.text[offset] == "}":
                return
            key_start = offset
            key, offset = decoder.raw_decode(source.text, offset)
            while source.text[offset].isspace():
                offset += 1
            offset += 1  # colon, already validated by json.loads
            while source.text[offset].isspace():
                offset += 1
            value_start = offset
            value, offset = decoder.raw_decode(source.text, offset)
            yield key, key_start, value_start, offset, value

    for key, start, value_start, end, value in entries(
        len(source.text) - len(source.text.lstrip())
    ):
        if key in {"definitions", "$defs"}:
            if isinstance(value, dict):
                for name, child_start, _, child_end, _ in entries(value_start):
                    symbols.append(
                        source.symbol(
                            name,
                            "definition",
                            source.byte(child_start),
                            source.byte(child_end),
                            parent=key,
                        )
                    )
        else:
            symbols.append(source.symbol(key, "key", source.byte(start), source.byte(end)))
    return symbols


def _yaml(source: _Source) -> list[SymbolInfo]:
    document = yaml.compose(source.text, Loader=yaml.SafeLoader)
    if not isinstance(document, yaml.MappingNode):
        return []
    symbols = []
    for index, (key, value) in enumerate(document.value):
        start = key.start_mark.index
        end = value.end_mark.index
        # Aliases share the original value node; use this entry's own boundary instead.
        if end < start:
            end = (
                document.value[index + 1][0].start_mark.index
                if index + 1 < len(document.value)
                else len(source.text)
            )
        end = start + len(source.text[start:end].rstrip())
        symbols.append(source.symbol(str(key.value), "key", source.byte(start), source.byte(end)))
    return symbols


def _markdown(source: _Source) -> list[SymbolInfo]:
    headings = []
    offset = 0
    fence = None
    for line in source.text.splitlines(keepends=True):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if marker:
            run = marker.group(1)
            if fence is None:
                fence = run
            elif run[0] == fence[0] and len(run) >= len(fence):
                fence = None
        elif fence is None:
            match = re.match(r"^(#{1,3})\s+(.+?)\s*#*\s*$", line)
            if match:
                headings.append((offset, len(match[1]), match[2]))
        offset += len(line)
    symbols = []
    ancestors = []
    for index, (start, level, name) in enumerate(headings):
        end = next(
            (entry[0] for entry in headings[index + 1 :] if entry[1] <= level), len(source.text)
        )
        end = start + len(source.text[start:end].rstrip())
        while ancestors and ancestors[-1][0] >= level:
            ancestors.pop()
        parent = ancestors[-1][1] if ancestors else None
        symbol = source.symbol(
            name,
            "heading",
            source.byte(start),
            source.byte(end),
            parent=parent,
            signature=f"{'#' * level} {name}",
        )
        symbols.append(symbol)
        ancestors.append((level, symbol.qualified_name))
    return symbols


def _toml_path(raw_key: str) -> list[str]:
    parsed = tomllib.loads(raw_key + " = 0")
    parts = []
    while isinstance(parsed, dict):
        key = next(iter(parsed))
        parts.append(key)
        parsed = parsed[key]
    return parts


def _unquoted(text: str, wanted: str):
    quote = None
    escaped = False
    for position, character in enumerate(text):
        if escaped:
            escaped = False
            continue
        if quote == '"' and character == "\\":
            escaped = True
        elif quote:
            if character == quote:
                quote = None
        elif character in "\"'":
            quote = character
        elif character == wanted:
            yield position


def _toml(source: _Source) -> list[SymbolInfo]:
    tomllib.loads(source.text)  # Reject malformed input instead of inventing ranges.
    lines = source.text.splitlines(keepends=True)
    symbols = []
    offset = 0
    index = 0
    table = None
    table_symbol = None
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        start = offset + len(line) - len(line.lstrip())
        if not stripped or stripped.startswith("#"):
            offset += len(line)
            index += 1
            continue
        if stripped.startswith("["):
            is_array = stripped.startswith("[[")
            opening = 2 if is_array else 1
            close = next(position for position in _unquoted(stripped, "]") if position >= opening)
            raw = stripped[opening:close]
            table_parts = _toml_path(raw)
            header = stripped[: close + opening]
            if table_symbol is not None:
                previous_end = len(source.text[:start].rstrip())
                table_symbol.end_byte = source.byte(previous_end)
                table_symbol.end_line = source.line(
                    max(table_symbol.start_byte, table_symbol.end_byte - 1)
                )
            table = ".".join(table_parts)
            table_symbol = source.symbol(
                table_parts[-1],
                "table",
                source.byte(start),
                source.byte(offset + len(line.rstrip())),
                parent=".".join(table_parts[:-1]) or None,
                signature=header,
            )
            symbols.append(table_symbol)
        else:
            equal = next(_unquoted(line, "="), None)
            if equal is not None:
                key_parts = _toml_path(line[:equal].strip())
                value = line
                while True:
                    try:
                        tomllib.loads(value)
                        break
                    except tomllib.TOMLDecodeError:
                        index += 1
                        if index >= len(lines):
                            return symbols
                        value += lines[index]
                parent_parts = ([table] if table else []) + key_parts[:-1]
                symbols.append(
                    source.symbol(
                        key_parts[-1],
                        "key",
                        source.byte(start),
                        source.byte(offset + len(value.rstrip())),
                        parent=".".join(parent_parts) or None,
                        signature=line.strip(),
                    )
                )
                offset += len(value) - len(line)
        offset += len(line)
        index += 1
    if table_symbol is not None:
        table_symbol.end_byte = source.byte(len(source.text.rstrip()))
        table_symbol.end_line = source.line(max(table_symbol.start_byte, table_symbol.end_byte - 1))
    return symbols


_SQL_PATTERN = re.compile(
    r"\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:TEMPORARY\s+)?"
    r"(FUNCTION|PROCEDURE|VIEW|TABLE)(?:\s+IF\s+NOT\s+EXISTS)?\s+([\w.]+)",
    re.I,
)
_SQL_NONCODE = re.compile(r"--[^\n]*|/\*[\s\S]*?\*/|'(?:''|[^'])*'|\$(\w*)\$[\s\S]*?\$\1\$")


def _sql(source: _Source) -> list[SymbolInfo]:
    masked = _SQL_NONCODE.sub(lambda match: " " * len(match[0]), source.text)
    symbols = []
    for match in _SQL_PATTERN.finditer(masked):
        end = masked.find(";", match.end())
        end = end + 1 if end >= 0 else len(source.text.rstrip())
        kind = {"VIEW": "view", "TABLE": "table"}.get(match[1].upper(), "function")
        signature = source.text[match.start() : match.end()]
        symbols.append(
            source.symbol(
                match[2],
                kind,
                source.byte(match.start()),
                source.byte(end),
                signature=" ".join(signature.split()),
            )
        )
    return symbols
