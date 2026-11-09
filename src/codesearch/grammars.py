"""Official grammar wheels; nothing is downloaded at runtime."""

from importlib import import_module

from tree_sitter import Language, Parser


def get_parser(language: str) -> Parser:
    module_name = "typescript" if language == "tsx" else language
    module = import_module(f"tree_sitter_{module_name}")
    factory = {
        "typescript": "language_typescript",
        "tsx": "language_tsx",
    }.get(language, "language")
    return Parser(Language(getattr(module, factory)()))
