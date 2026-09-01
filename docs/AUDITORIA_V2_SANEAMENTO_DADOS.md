# Auditoria V2 - Saneamento de Dados

Escopo deste pacote:

- SKUs ativos sem Produto-Pai valido.
- Pedidos antigos do Gerador sem `cliente_id`.
- Itens manuais antigos sem `cadastro_pendente`.
- Estoque lab sem material master em `materiais`.

## Comando seguro

Dry-run:

```bash
python scripts/saneamento_audit_v2.py --report reports/audit_v2/saneamento_audit_v2.json
```

Apply controlado:

```bash
python scripts/saneamento_audit_v2.py --apply --confirm APPLY_AUDIT_V2_SANITATION --report reports/audit_v2/saneamento_audit_v2_apply.json
```

Nao executar `--apply` sem revisar o JSON gerado no dry-run.

## Garantias

- O modo padrao e `dry-run`.
- O script nao apaga documentos.
- O script nao faz merge de clientes.
- O script so planeja `insert_one` e `update_one`.
- `--apply` exige confirmacao textual.
- Produto-Pai usa a colecao real `produtos_pai`; a colecao legada `produto_pais` e apenas lida como fallback.

## Regras aplicadas

1. SKU sem Produto-Pai:
   - Se o Produto-Pai existe em `produtos_pai`, nao faz nada.
   - Se existe candidato unico por tenant, cliente e nome base, apenas vincula o SKU.
   - Se nao existe candidato e o cliente e valido, planeja criar Produto-Pai e vincular o SKU.
   - Se houver ambiguidade, registra issue e nao altera.

2. Pedido antigo do Gerador:
   - Recupera `cliente_id` por CNPJ unico no CRM.
   - Se nao houver CNPJ unico, tenta nome unico.
   - Se houver ambiguidade, registra issue e nao altera.

3. Item manual:
   - Para item sem `sku_id` e codigo vazio/A definir/NA, marca `cadastro_pendente`.
   - Preserva itens ja existentes em `cadastro_pendente_items`.

4. Estoque lab:
   - Se ja existe material por codigo ou nome, vincula o item de estoque com `material_master_id`.
   - Se nao existe, planeja criar material master em `materiais`.
   - Codigos automaticos de saneamento usam faixa reservada `TIPO2-90000+` para reduzir colisao com sequencias operacionais.
