# Comparação e melhorias incorporadas

Análise de 08/11/2026: referência local `C:/git/pessoal/jcodemunch-mcp-main`, versão declarada 1.108.426; produto atualizado em `C:/git/pessoal/codeSearch`, versão 0.2.0. Foram examinados código, contratos e testes, não apenas a lista anunciada de funcionalidades.

## O que a referência oferecia a mais ou melhor

| Área e evidência na referência | codeSearch 0.1 | Incorporado no codeSearch 0.2 |
|---|---|---|
| Ranking: `tools/search_symbols.py` e testes de ordenação | BM25 com pouco controle de escopo | Nome exato primeiro, desempate determinístico, filtros antes do limite, nomes qualificados e partes snake_case/camelCase |
| Metadados: `parser/symbols.py`, `parser/extractor.py` | Nome, assinatura, resumo e linhas | Ownership, decorators, docstrings, chamadas/bases sintáticas, intervalo UTF-8 e IDs sem colisão na mesma linha |
| Imports: `parser/imports.py` | Extração limitada, aliases/multilinhas incompletos | AST Python/JS/TS, imports múltiplos, relativos, aliases, type-only, reexports e limites dinâmicos explícitos |
| Contexto: `tools/get_symbol.py`, `tools/get_context_bundle.py` | Recuperação individual por nome | Lotes por ID, erros parciais, deduplicação, bundles e contexto lexical por tarefa |
| Busca textual: `tools/search_text.py` | Grep literal sem contexto | Regex com timeout efetivo, contexto e símbolo envolvente; filtros FTS antes da paginação |
| Dependências: `tools/find_importers.py`, `get_dependency_graph.py`, `get_blast_radius.py` | Apenas lista de imports | Importadores, grafo, impacto potencial e ciclos, com evidência e incerteza |
| Relações e visão geral: ferramentas de chamadas/herança e outlines | Sem navegação entre símbolos | Hierarquias conservadoras de chamadas/herança e contagens por diretório |
| Persistência: `storage/sqlite_store.py`, `parser/parse_cache.py`, `tools/index_folder.py` | Hash de todo conteúdo em cada varredura | Reuso por metadados, revisão de parser, snapshots transacionais, diagnósticos persistentes e última mudança do índice |

Os caminhos da primeira coluna são relativos a `src/jcodemunch_mcp/`. A referência contém uma cobertura de linguagens e integrações muito maior. As vantagens acima foram implementadas independentemente no produto local, sem importar ou copiar seus módulos/testes. O arquivo LICENSE da referência declara condições próprias; ele não foi transplantado nem atribuído ao codeSearch.

## Melhorias de correção além da aproximação funcional

- O orçamento de contexto inclui todo o objeto JSON retornado, inclusive modo compacto e metadados. Fontes cortadas têm cursor para continuação; não anunciamos economia de tokens sem medição.
- Regex usa interrupção por timeout da biblioteca `regex`; conferir relógio apenas entre chamadas não interromperia uma expressão patológica dentro de uma linha.
- IDs `file:line` continuam disponíveis, mas colisões são erros explícitos. `symbol_id` diferencia método/classe na mesma linha e sobrecargas.
- Um pedido composto fixa um snapshot. Alterar um arquivo durante a consulta não mistura coordenadas antigas com conteúdo novo.
- Reuso do conteúdo mantém checagens de confinamento, handles, regras de ignore e substituição de arquivos. `force=true` continua disponível para verificação integral.
- Caminhos dinâmicos, ambíguos ou dependentes do CWD/PATH não viram arestas inventadas. Parsing malformado gera diagnóstico e cobertura incompleta.

## Evidência de ganho de leitura

Executado com `uv run python scripts/benchmark_index.py`, em 250 arquivos Python gerados localmente; resultado bruto em `test-results/index-benchmark.json`:

| Varredura | Corpos lidos | Bytes lidos | Arquivos reutilizados |
|---|---:|---:|---:|
| Inicial | 250 | 2.562.530 | 0 |
| Sem mudanças | 0 | 0 | 250 |
| Um arquivo editado | 1 | 38 | 249 |
| Verificação forçada | 250 | 2.552.321 | 0 |

A versão anterior relia todos os corpos admitidos a cada varredura, mesmo quando só o parsing era incremental. O ganho demonstrado é de I/O de conteúdo; ainda existe enumeração e validação de metadados. Tempos dependem do filesystem, cache e tamanho do projeto; não houve benchmark comparativo de velocidade contra jcodemunch. Ignores têm contadores de leitura separados.

## Diferenças que permanecem

| Capacidade da referência | Situação e decisão neste produto |
|---|---|
| Catálogo muito maior de linguagens | 12 famílias com extração testada; priorizadas correção de Python/TS/Java e adição de Bash/TOML. A profundidade não é idêntica entre linguagens |
| Enriquecimento por modelos/embeddings e integrações externas | Mantido funcionamento local sem credenciais, downloads de modelos ou chamadas de IA |
| Resolução por compiladores, LSP/SCIP e integrações de IDE | Não incorporada; exige serviços/índices e contratos próprios. Hierarquias atuais são candidatos estáticos |
| Múltiplos repositórios e seleção/clonagem remota | Uma pasta por processo/container; vários containers podem atender pastas diferentes |
| Histórico Git e consultas além do snapshot atual | get_index_changes informa a última alteração do índice; não substitui histórico de commits |
| Análises globais de uso/código morto | Sem conclusões de ausência ou segurança para exclusão; cobertura e dependências não resolvidas permanecem explícitas |

O conjunto passou de 15 para 26 ferramentas, preservando as anteriores. Consulte [README](../README.md) para parâmetros, limites, conexão MCP e operação com Podman. O registro final de validação fica em [UPGRADE.md](UPGRADE.md).
