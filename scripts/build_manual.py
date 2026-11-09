"""Build the offline HTML and Markdown manual from editorial sources and real MCP recordings."""

from __future__ import annotations

import base64
import html
import json
import re
import unicodedata
from pathlib import Path

from markdown_it import MarkdownIt

from codesearch.server import TOOLS

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
SOURCE = DOCS / "manual"


def slug(value: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


def code(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def catalog_markdown(entries: list[dict]) -> str:
    parts = []
    for number, entry in enumerate(entries, 1):
        parts.append(
            f"### {number:02d}. {entry['name']}\n\n"
            f"**{entry['group']}.** {entry['purpose']}\n\n"
            f"> {entry['prompt']}\n\n"
            f"```json\n{code(entry['args'])}\n```\n\n"
            f"**Parâmetros:** {entry['parameters']}\n\n"
            f"**O que retorna:** {entry['output']}\n\n"
            f"**Atenção ao interpretar:** {entry['note']}\n"
        )
    return "\n".join(parts)


def catalog_html(entries: list[dict], schemas: dict[str, dict]) -> str:
    cards = []
    escape = html.escape
    for number, entry in enumerate(entries, 1):
        name = escape(entry["name"])
        search = escape(" ".join(str(value) for value in entry.values()))
        cards.append(f"""
<details class="tool-card" id="tool-{name}" data-search="{search}"
 data-group="{escape(entry["group"])}">
 <summary><span class="tool-number">{number:02d}</span><span>
 <span class="tool-name">{name}</span><span class="tool-purpose">{escape(entry["purpose"])}</span>
 </span><span class="expand" aria-hidden="true">+</span></summary>
 <div class="tool-body"><span class="tag">{escape(entry["group"])}</span>
 <blockquote>{escape(entry["prompt"])}</blockquote>
 <pre><code class="language-json">{escape(code(entry["args"]))}</code></pre>
 <p><strong>Parâmetros:</strong> {escape(entry["parameters"])}</p>
 <p><strong>O que retorna:</strong> {escape(entry["output"])}</p>
 <p class="note"><strong>Ao interpretar:</strong> {escape(entry["note"])}</p>
 <button class="record-link" data-tool="{name}">Ver chamada gravada ↗</button>
 <details class="schema"><summary>Contrato de entrada completo (MCP)</summary>
 <pre><code>{escape(code(schemas[entry["name"]]))}</code></pre></details>
 </div></details>""")
    return (
        """
<div class="tool-filters">
 <label for="tool-search">Buscar por nome, tarefa ou parâmetro</label>
 <input id="tool-search" type="search" placeholder="Ex.: impacto, symbol_id, regex…">
 <label for="tool-group">Categoria</label><select id="tool-group">
 <option value="">Todas as categorias</option>"""
        + "".join(
            f"<option>{escape(group)}</option>"
            for group in dict.fromkeys(e["group"] for e in entries)
        )
        + """</select><p id="tool-count" role="status">26 ferramentas</p></div>
<div id="tool-cards">"""
        + "".join(cards)
        + "</div>"
    )


PLAYER = """
<section class="player" id="demo-player" aria-label="Demonstrações gravadas">
 <div class="player-top"><span class="tag">REPLAY · MCP REAL</span>
 <span id="recording-meta"></span></div>
 <label for="demo-scenario">Escolha um roteiro</label>
 <select id="demo-scenario"></select>
 <div class="player-controls">
 <button id="demo-prev" aria-label="Chamada anterior">← Anterior</button>
 <button id="demo-play">Reproduzir</button>
 <button id="demo-next" aria-label="Próxima chamada">Próxima →</button>
 <span id="demo-progress" role="status"></span></div>
 <h3 id="demo-tool"></h3><p id="demo-label"></p>
 <div class="demo-grid"><div><h4>Argumentos enviados</h4>
 <pre><code id="demo-args"></code></pre><p id="demo-note" class="note"></p></div>
 <div><h4>Resposta recebida</h4><pre class="demo-output" tabindex="0"
 aria-label="Resposta JSON completa, área rolável"><code id="demo-result"></code></pre></div></div>
 <p class="player-foot">Gravação da loja fictícia. Os controles reproduzem respostas salvas;
 não fazem chamadas ao seu servidor.</p>
</section>
"""


def main() -> None:
    entries = json.loads((SOURCE / "tools.json").read_text(encoding="utf-8"))
    recording = json.loads((SOURCE / "demo-results.json").read_text(encoding="utf-8"))
    names = [entry["name"] for entry in entries]
    assert len(names) == len(set(names)) == len(TOOLS) == 26
    assert set(names) == set(TOOLS) == {row["tool"] for row in recording["recordings"]}
    schemas = {row["name"]: row["inputSchema"] for row in recording["schemas"]}
    for entry in entries:
        # Catch drift in example keyword names before publishing the reference.
        schema = schemas[entry["name"]]
        assert set(entry["args"]) <= set(schema["properties"]), entry["name"]
        assert set(schema.get("required", [])) <= set(entry["args"]), entry["name"]

    base = (SOURCE / "guia-base.md").read_text(encoding="utf-8")
    markdown = base.replace("<!-- TOOL_CATALOG -->", catalog_markdown(entries))
    (DOCS / "MANUAL.md").write_text(markdown, encoding="utf-8")

    parser = MarkdownIt("commonmark", {"html": True}).enable("table")
    tokens = parser.parse(base)
    navigation = []
    for index, token in enumerate(tokens):
        if token.type == "heading_open":
            title = tokens[index + 1].content
            anchor = slug(title)
            token.attrSet("id", anchor)
            if token.tag == "h2":
                navigation.append(f'<a href="#{anchor}">{html.escape(title)}</a>')
    body = parser.renderer.render(tokens, parser.options, {})
    body = body.replace("<!-- TOOL_CATALOG -->", catalog_html(entries, schemas))
    body = body.replace("<!-- DEMO_PLAYER -->", PLAYER)
    for path in sorted((SOURCE / "assets").glob("*.svg")):
        encoded = base64.b64encode(path.read_bytes()).decode()
        body = body.replace(f"manual/assets/{path.name}", f"data:image/svg+xml;base64,{encoded}")

    template = (SOURCE / "template.html").read_text(encoding="utf-8")
    replacements = {
        "{{STYLE}}": (SOURCE / "manual.css").read_text(encoding="utf-8"),
        "{{SCRIPT}}": (SOURCE / "manual.js").read_text(encoding="utf-8"),
        "{{BODY}}": body,
        "{{NAV}}": "\n".join(navigation),
        "{{DATA}}": json.dumps(
            {"recording": recording, "catalog": entries}, ensure_ascii=False
        ).replace("<", "\\u003c"),
        "{{VERSION}}": html.escape(recording["version"]),
        "{{CALL_COUNT}}": str(recording["call_count"]),
    }
    for marker, value in replacements.items():
        template = template.replace(marker, value)
    assert not re.search(r"\{\{[A-Z_]+\}\}", template)
    (DOCS / "MANUAL.html").write_text(template, encoding="utf-8")
    print(
        f"Built MANUAL.md + MANUAL.html: {len(names)} tools, 3 embedded SVGs, "
        f"{recording['call_count']} recorded calls."
    )


if __name__ == "__main__":
    main()
