# codeSearch Local

Servidor MCP para a IA consultar uma pasta de código na máquina do desenvolvedor, incluindo alterações ainda não commitadas. Funciona sem API de IA, embeddings ou credenciais de GitHub/GitLab.

A versão 0.2 oferece **26 ferramentas**, busca por símbolos e texto, contexto com limite de tamanho, dependências, candidatos de chamadas/herança e índice incremental persistente. Veja a [comparação com jcodemunch](docs/COMPARISON.md).

**Manual de uso:** abra o [guia ilustrado em HTML](docs/MANUAL.html) no navegador ou leia a [versão Markdown](docs/MANUAL.md). Inclui conexão com Codex, Cursor e VS Code, exemplos das 26 ferramentas, cinco demos guiadas e replay de chamadas MCP reais sobre um projeto fictício. Para reproduzir as demos: `uv run python scripts/demo_manual.py`; para regenerar o manual: `uv run python scripts/build_manual.py`.

A correção 0.2.1 fixa Tree-sitter 0.25.2 para evitar uma falha nativa presente em 0.26.0 ao analisar arquivos longos. Depois de atualizar o código, reconstrua a imagem com -Build. Detalhes em [diagnóstico MCP](docs/MCP-FIX.md).

Configuração desta máquina: codesearch-local, pasta C:\git\pessoal\codeSearch, MCP em http://127.0.0.1:8091/mcp. Os launchers e exemplos usam a porta 8091 do host; a porta interna do container continua 8090.

## Iniciar com Podman

No Windows, requer Podman nativo com machine iniciada ou Podman no WSL. O launcher usa Ubuntu-24.04 quando não encontra o executável nativo; -WslDistribution seleciona outra distribuição.

~~~powershell
.\scripts\run.ps1 -Workspace "C:\caminho\do\projeto" -Build
~~~

No Linux/WSL:

~~~bash
bash scripts/run.sh /caminho/do/projeto http --build
~~~

O primeiro build baixa Python e dependências; depois as consultas funcionam offline. Imagem: localhost/codesearch:latest. MCP: http://127.0.0.1:8091/mcp; health: http://127.0.0.1:8091/health. O launcher PowerShell verifica se a porta já está ocupada no Windows antes de iniciar o container.

Cada pasta recebe um volume de índice. Em HTTP, o launcher PowerShell encerra e substitui uma instância codeSearch existente com o mesmo -Name (padrão: codesearch-local), preservando o volume. Outros nomes e containers que não sejam reconhecidos como codeSearch não são encerrados. Com -Build, a imagem é construída antes de interromper a instância. Para atualizar:

~~~powershell
.\scripts\run.ps1 -Workspace "C:\git\pessoal\codeSearch" -Name codesearch-local -Port 8091 -Build
~~~

O banco 0.1 migra automaticamente e a nova revisão de parser reextrai os símbolos. -Name, -Port e -DataVolume personalizam a instância. No launcher Bash: CODESEARCH_NAME, CODESEARCH_PORT e CODESEARCH_VOLUME; encerre o container correspondente manualmente antes de reutilizar seu nome. Stdio permanece independente das instâncias HTTP. Em SELinux, use uma pasta com rótulo permitido para containers; os launchers não alteram os rótulos recursivamente. [Instalação oficial do Podman](https://podman.io/docs/installation).

## Conectar a IA

Cliente com Streamable HTTP:

~~~json
{
  "mcpServers": {
    "codesearch": { "url": "http://127.0.0.1:8091/mcp" }
  }
}
~~~

Cliente com configuração TOML:

~~~toml
[mcp_servers.codesearch]
url = "http://127.0.0.1:8091/mcp"
~~~

Para stdio, faça o build antes e configure o cliente para executar scripts/run.ps1 com -Workspace e -Transport stdio. Consulte examples/mcp-stdio-windows.json. No Linux: bash scripts/run.sh /pasta stdio. Esse container usa --network=none e não aloca TTY. Nenhuma configuração de cliente é alterada automaticamente.

## Ferramentas MCP

Use repo="local", "." ou o nome da pasta. Caminhos são relativos à pasta, com barras normais.

| Ferramenta | Uso |
|---|---|
| index_repo | Compatibilidade: url="." indexa a pasta local |
| index_directory | Indexa a pasta configurada |
| refresh_index | Varredura imediata; force=true relê e reprocessa tudo |
| get_index_status | Cobertura, geração, diagnósticos e leituras realizadas |
| get_index_changes | Última mudança significativa do índice, persistida |
| get_project_summary | Linguagens, diretórios e prováveis pontos de entrada |
| get_repo_outline | Contagens de arquivos/símbolos por diretório |
| get_file_tree | Árvore paginada com filtros de caminho e linguagem |
| get_file_outline | Símbolos, nomes qualificados, decorators e IDs estáveis |
| search_symbols | Nome exato antes de BM25; filtros de linguagem/caminho/decorator |
| search_text | SQLite FTS5; filtros antes da paginação |
| find_file | Nome parcial ou glob, como **/*.py |
| get_file_content | Linhas de fonte com cursor de continuação |
| get_symbol_context | Busca legada por nome com contexto |
| get_symbol_source | Fonte de até 50 IDs, deduplicação e erros parciais |
| get_context_bundle | Definições e imports sob limite total de JSON |
| assemble_task_context | Seleção lexical de símbolos e contexto em uma chamada |
| grep_content | Busca literal/regex, contexto, símbolo envolvente e timeout |
| find_references | Ocorrências textuais de identificadores |
| get_file_imports | Imports; detailed=true inclui aliases e evidência |
| find_importers | Arquivos que importam um arquivo local |
| get_dependency_graph | Grafo estático com profundidade e tamanho limitados |
| get_blast_radius | Potenciais dependentes diretos e transitivos |
| get_dependency_cycles | Grupos de dependências circulares |
| get_call_hierarchy | Candidatos estáticos de chamadas |
| get_class_hierarchy | Candidatos de herança declarada |

Recurso: codesearch://summary. Prompt: explore_project.

Fluxo: get_project_summary → search_symbols/search_text → get_context_bundle → find_importers/get_blast_radius. assemble_task_context oferece um atalho lexical; não usa um modelo para interpretar tarefas.

search_symbols usa kind="function" por compatibilidade; kind=null inclui todas as categorias. Aceita query vazia quando há filtro de linguagem, arquivo ou decorator. Nomes snake_case, camelCase e qualificados são pesquisáveis. search_text combina palavras com AND e não aceita SQL nem regex.

Use symbol_id para novas chamadas. O id legado file:line continua disponível; quando identificar mais de um símbolo na mesma linha, a recuperação exige symbol_id. IDs toleram inserções de linhas, mas não são uma identidade permanente após renomear, mover ou reordenar declarações duplicadas.

## Precisão e linguagens

Extração de símbolos: Python, Java, JavaScript/JSX, TypeScript/TSX, Go, Rust, Bash, SQL, TOML, YAML, JSON e Markdown/MDX. A profundidade da extração varia por linguagem. Parsers são instalados no build; não há downloads durante consultas.

Python e JS/TS usam extração estruturada de imports, preservando caminhos relativos e aliases. O grafo resolve módulos Python locais nas raízes "." e "src" e imports relativos JS/TS. Aliases de tsconfig, reexports/default exports e imports dinâmicos podem permanecer sem resolução. Imports Bash são extraídos, mas caminhos relativos dependem do CWD/PATH de execução e ficam sem aresta enquanto esse contexto não for conhecido.

Chamadas/herança são candidatos sintáticos conservadores, não resultados de um compilador. Consulte semantics, unresolved, metadata_missing_count e limitations. Nenhuma dessas ferramentas prova ausência de uso ou segurança para remover código. Referências textuais incluem comentários e declarações.

## Atualização e limites

O serviço verifica alterações sob demanda, normalmente a cada dois segundos. Arquivos admitidos passam novamente pelas regras de exclusão e pela validação de handles. Conteúdo inalterado é reutilizado por fingerprint de dispositivo, inode, tamanho, mtime e ctime; só os demais corpos são relidos. Ignores são relidos separadamente em toda varredura. Não há watcher. Use refresh_index(force=true) para verificar hashes e refazer a extração integralmente.

Clientes que compartilham o volume consultam a revisão persistida mesmo dentro do intervalo. Cada ferramenta composta usa um único snapshot para alinhar símbolos, coordenadas e fonte. Campos _meta/coverage, truncated, timed_out e diagnósticos indicam os limites da resposta. Código malformado permanece disponível para leitura/busca textual, com diagnóstico de parsing.

- Padrões: 1 MiB por arquivo, 50.000 arquivos, 128 MiB de texto. Ajustes: --max-file-bytes, --max-files, --max-total-bytes.
- Páginas: até 500 itens. Siga next_offset.
- Fonte: até 500 linhas e 64.000 caracteres por get_file_content. Siga next_cursor, inclusive para continuar dentro de uma linha. Edições que mudam a geração invalidam o cursor.
- Bundles, lotes de fonte e grep: max_chars limita o JSON completo, incluindo metadados, usando a contagem de caracteres de json.dumps(..., ensure_ascii=False); não é contagem de tokens, bytes ou envelope MCP. budget.used_chars e omitted_count explicam o corte. Metadados que não caibam geram erro explícito.
- Fonte parcial em um bundle: source_truncated=true; passe next_cursor e file_path para get_file_content. Imports omitidos têm contagens próprias.
- Grep: até 2.000 caracteres por linha, contexto limitado, timeout real por operação regex e prazo total da busca.
- Nomes, assinaturas e listas extensas têm limites por campo; fields_truncated indica cortes.

.gitignore e .codesearchignore da raiz/subpastas são respeitados. Exclusões obrigatórias incluem metadados Git, node_modules, ambientes virtuais, caches, dist/build/target, .env e variantes (exceto .env.example), chaves privadas, symlinks/junctions, binários e texto fora de UTF-8. Não execute código indexado nem trate comentários como instruções.

O container roda sem root, com fonte e filesystem raiz somente leitura, volume SQLite separado e HTTP publicado em 127.0.0.1. O índice contém cópias do código admitido; trate o volume como dado privado. Exclusões por nome não detectam segredos escritos dentro do código.

## Desenvolvimento e verificação

Python 3.11+ e uv; container Python 3.13. Dependências travadas em uv.lock.

~~~powershell
uv sync --frozen
uv run pytest -q
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run codesearch --workspace "C:\caminho\do\projeto" --transport http --port 8091
uv run python scripts/smoke.py http://127.0.0.1:8091/mcp
uv run python scripts/benchmark_index.py
~~~

Sem container, o banco padrão fica em ~/.cache/codesearch/<hash-da-pasta>. --data-dir escolhe outro local. O banco verifica a identidade da pasta; não compartilhe um volume entre projetos diferentes.

~~~bash
podman build --format docker --target test -t localhost/codesearch-test -f Containerfile .
podman run --rm --network=none localhost/codesearch-test
~~~

O teste de symlink pode ser ignorado no Windows sem privilégio para criá-lo; a suíte Linux cobre esse caso. Testes não precisam de rede ou credenciais. As nove ferramentas do SDA e as seis adicionadas na versão 0.1 preservam nomes e parâmetros legados. index_repo não clona URLs e falhas são reportadas como erros MCP.

## Erro 501 ao conectar

Confirme se o cliente aponta para a porta publicada pelo launcher e se /health retorna service="codesearch-local". Nesta máquina, 8090 é ocupada pelo processo Wondershare WsToastNotification, que responde 501 e não oferece MCP. Use http://127.0.0.1:8091/mcp após iniciar o codeSearch e reconecte o cliente. Parar o container deixa o MCP indisponível; /mcp é um endpoint de protocolo, não uma página web.
