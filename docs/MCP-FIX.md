# Correção MCP — 08/11/2026

## Duas falhas distintas

1. A configuração ativa do Codex ainda usava `http://127.0.0.1:8090/mcp`. Nessa porta, o processo Windows Wondershare WsToastNotification devolvia HTTP 501, inclusive em `/health`. O codeSearch atendia na porta 8091. A entrada `mcp_servers.codesearch-local.url` em `~/.codex/config.toml` foi corrigida, sem alterar outras opções. Reconecte o servidor MCP ou reinicie o cliente para recarregar a configuração.
2. A consulta direta na porta correta reproduziu uma queda ao indexar RHFlow. O Podman registrou saída 139, sem OOM. Com faulthandler, a falha apontou para `imports.py`, na leitura de `node.start_point.row`. O código do projeto consultado foi montado somente leitura e não foi modificado.

## Causa e correção

Tree-sitter 0.26.0 contém um defeito na contagem de referências dos campos de Point, descrito no [issue oficial #500](https://github.com/tree-sitter/py-tree-sitter/issues/500). A corrupção de memória pode aparecer em arquivos com coordenadas além do cache de inteiros pequenos do Python.

A versão **0.2.1** fixa a dependência em **tree-sitter==0.25.2**, atualiza `uv.lock` e a revisão do parser para reextrair índices existentes. O container passa a habilitar faulthandler para registrar stacks em eventuais falhas nativas futuras.

`tests/test_parser_process.py` gera JavaScript com 400 declarações após a linha 300, extrai símbolos/imports repetidamente, valida coordenadas e força coleta de memória. O teste roda em subprocesso para que uma falha nativa não encerre o pytest. Com 0.26.0 reproduziu access violation; com 0.25.2 passou.

## Inicialização manual

```powershell
& "C:\git\pessoal\codeSearch\scripts\run.ps1" -Workspace "C:\Projetos\DC\RHFlow" -Port 8091 -Build
```

Endpoint do cliente: `http://127.0.0.1:8091/mcp`. `/health` deve identificar `codesearch-local`, versão 0.2.1. O launcher substitui a instância reconhecida com o mesmo nome e preserva o volume do índice.

## Validação concluída

- Windows: **201 testes aprovados, 1 ignorado** por privilégio de symlink; Ruff lint/format aprovados.
- Linux/Podman sem rede: **202 testes aprovados**, incluindo a regressão em subprocesso.
- Imagem `localhost/codesearch:latest` reconstruída como **0.2.1**.
- No RHFlow real, montado somente leitura: `get_project_summary`, quatro chamadas de `get_file_tree` e `refresh_index(force=true)` concluíram; **647 arquivos admitidos e 4.400 símbolos**, sem erros de parsing ou queda.
- O índice informou cobertura parcial por 19 arquivos binários e 3 acima do limite por arquivo; isso não é falha do MCP. Nenhum limite foi alterado para ocultar exclusões.
- Consulta adicional à árvore/status concluiu em aproximadamente 30 segundos; health retornou HTTP 200 e container saudável.
- Configuração Codex validada como TOML, alterando apenas a URL do servidor codeSearch. É necessário recarregar a conexão no cliente.
- Containers e volumes de diagnóstico encerrados/removidos após a validação; inicialização principal permanece manual.

Evidência local: `test-results/rhflow-segfault-before.log`, `rhflow-exit-before.log`, `rhflow-fixed-mcp.log`, `rhflow-runtime-after.log` e `fix021-linux-tests.log`.
