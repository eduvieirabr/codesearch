# Registro da atualização 0.2.0

Pedido: comparar a referência local jcodemunch-mcp-main e incorporar melhorias ao codeSearch local. Implementação em 08/11/2026, sem alterar a referência nem o repositório SDA original.

## Entrega

- 26 ferramentas MCP: 15 preservadas e 11 novas.
- Parsing enriquecido, IDs estáveis, imports estruturados e suporte adicional a Bash/TOML.
- Ranking exato, filtros anteriores à paginação, regex com timeout e contexto com orçamento JSON.
- Dependências, impacto, ciclos e hierarquias com evidência e limites explícitos.
- Reuso incremental por metadados, snapshots consistentes, diagnósticos persistentes e migração do banco.
- README e AGENTS atualizados; análise detalhada em [COMPARISON.md](COMPARISON.md).

## Revisão independente

Quatro achados reproduzidos e corrigidos com regressões:

1. Crescimento do JSON após a reserva de orçamento: considerar `false`/`null` antes de admitir conteúdo.
2. Colisão entre símbolo de pacote Python e submódulo: classificar como ambígua, sem aresta presumida.
3. Imports Bash relativos: depender de CWD/PATH desconhecido, sem assumir a pasta do script.
4. Árvores Tree-sitter com erro: registrar diagnóstico e cobertura incompleta, preservando fonte/FTS.

Revisão final: aprovada após novas reproduções dos quatro casos e leitura da documentação. Sem achados materiais pendentes.

## Validação

- Windows: `uv run pytest -q` — **200 aprovados, 1 ignorado** (privilégio de symlink indisponível).
- `uv run ruff check src tests scripts` e `uv run ruff format --check src tests scripts` — aprovados.
- Clientes FastMCP reais exercitam todas as 26 ferramentas, recursos, prompts e erros; subprocesso stdio incluído na suíte.
- Benchmark reproduzível: 250 corpos lidos inicialmente, zero sem mudanças, um após edição; sem extrapolar para economia de tokens ou velocidade universal.
- Testes cobrem migração schema 1→2, revisão de parser, edição concorrente, troca de arquivos, políticas de ignore, limites de contexto, regex patológica e continuação UTF-8/CRLF.

- Linux/Podman, `--network=none`: **201 aprovados, nenhum ignorado**. Log: `test-results/upgrade-linux-tests.log`.
- Build de teste e runtime concluídos; imagem publicada apenas no armazenamento local como `localhost/codesearch:latest`. A imagem anterior permanece como `localhost/codesearch:0.1.0`.
- Verificação em container temporário: 26 tools, fonte em bundle, grafo, atualização sem releitura, edição incremental, montagem fonte somente leitura e conexão stdio via PowerShell — aprovadas. Log: `test-results/upgrade-runtime-check.log`.

## Instância atualizada

- Container `codesearch-local`, versão **0.2.0**, MCP em **http://127.0.0.1:8091/mcp**.
- Pasta `C:/git/pessoal/codeSearch` montada somente leitura em `/workspace`; volume anterior `codesearch-ccd72a0c719d` preservado.
- Migração real validada: geração 2, parser `2-rich-symbols-2`, 62 arquivos e 474 símbolos na primeira consulta após a atualização; nenhum diagnóstico de parsing. Contagens variam com novas edições.
- Healthcheck aprovado; usuário `10001:10001` e filesystem raiz somente leitura confirmados.
- Container temporário encerrado. O serviço que já ocupava a porta 8090 não foi alterado.
- Sem publicação remota, configuração automática de clientes, mudança no código de referência ou commit automático.
