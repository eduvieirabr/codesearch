# Loja de demonstração

Projeto fictício para explorar o codeSearch. Os arquivos são dados de entrada
para análise estática: não é necessário instalar ou executar a aplicação.

- `shop/pricing.py`: cálculo de desconto e total em centavos.
- `shop/checkout.py`: usa o cálculo de total.
- `shop/api.py`: usa o checkout, formando uma dependência transitiva.
- `shop/models.py`: classes para demonstrar herança.
- `shop/cycle_a.py` e `shop/cycle_b.py`: ciclo de imports intencional.

Na raiz do codeSearch, execute:

```powershell
uv run python scripts/demo_manual.py
```

O roteiro copia esta pasta para um diretório temporário, consulta um servidor
MCP com um cliente FastMCP real e altera somente a cópia temporária para
demonstrar a atualização incremental. Nenhum arquivo desta aplicação é executado.
As respostas são gravadas em `docs/manual/demo-results.json`.

Para explorar esta pasta no seu cliente de IA:

```powershell
uv run codesearch --workspace ./examples/manual-project --transport http --port 8092
```

Conecte o cliente a `http://127.0.0.1:8092/mcp`. A porta separada permite manter
outra instância em 8091. Veja o manual em `docs/MANUAL.html`.
