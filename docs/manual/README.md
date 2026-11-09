# Fontes do manual de uso

Entregas: [MANUAL.html](../MANUAL.html) (navegável, offline e com imagens incorporadas)
e [MANUAL.md](../MANUAL.md) (texto editável com referências relativas às imagens).

## Conteúdo e geração

- `guia-base.md`: introdução, instalação, conexão, demos e interpretação dos resultados.
- `tools.json`: descrição, exemplo, parâmetros e limites de cada ferramenta.
- `assets/*.svg`: ilustrações técnicas originais; não são screenshots de clientes.
- `template.html`, `manual.css`, `manual.js`: apresentação e replay offline.
- `demo-results.json`: argumentos, respostas e schemas reais gravados via MCP stdio.
- `../../examples/manual-project/`: código fictício; usado como dados, sem execução.

Na raiz do codeSearch:

```powershell
uv sync --frozen
uv run python scripts/demo_manual.py
uv run python scripts/build_manual.py
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
```

O gerador usa `markdown-it-py`, já presente nas dependências travadas transitivas
de Rich/FastMCP. Não instala pacotes adicionais. O roteiro usa um processo stdio
real e um cliente FastMCP. O projeto de exemplo é copiado para uma pasta temporária;
a edição que demonstra invalidação incremental acontece apenas nessa cópia.

O gerador confere a correspondência entre as 26 ferramentas, o catálogo, os schemas
e as gravações. Os schemas apresentados no HTML são os retornados pelo servidor
na última gravação. Antes de documentar uma versão nova, regenere as gravações.

O replay usa somente dados incorporados ao HTML, sem fetch, CDN ou analytics.
Os botões não executam ferramentas nem editam arquivos. Links para as fontes
editoriais e o código exigem manter a estrutura do repositório; a leitura do
manual e a reprodução das demos funcionam com o HTML isolado.

Para verificar HTTP separadamente, inicie uma instância de demonstração em 8092
e execute `uv run python scripts/smoke.py http://127.0.0.1:8092/mcp`.
