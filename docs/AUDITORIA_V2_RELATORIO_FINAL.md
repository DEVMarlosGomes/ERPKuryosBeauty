# Auditoria V2 - Relatorio da Rodada

Data: 2026-08-24
Branch: `audit-v2-crm-pd-sku-orders`
Commit base: `3eefc93327dad017671763af8ff4aa2734be6922`

## Discovery

O arquivo `C:\Users\MARLOS\Downloads\AUDITORIA_V2_CODEX_KURYOS.md` foi lido integralmente antes de qualquer alteracao de codigo.

Fluxo real confirmado:

Cliente -> Projeto -> Amostra/Variacao -> Card P&D -> Requisicao P&D -> Desenvolvimento -> Formula -> Testes/Estabilidade -> Aprovacao -> Resultado do Cliente -> Produto-Pai -> SKU -> Pedido em negociacao -> CGI -> Pedido confirmado/OP.

## Entregas desta rodada

- Criada a matriz de achados em `docs/AUDITORIA_V2_MATRIZ.md`.
- Criado o fluxo real em `docs/AUDITORIA_V2_FLUXO.md`.
- Criado o mapa de status em `docs/AUDITORIA_V2_STATUS_MAP.md`.
- Criado o registro de decisoes em `docs/AUDITORIA_V2_DECISOES.md`.
- Criada a area de reports em `reports/audit_v2/README.md`.
- Gerador de Pedidos agora exige `cliente_id` cadastrado no backend para `origem=gerador`.
- Gerador de Pedidos limpa CNPJ/endereco/e-mail/telefone quando o texto digitado nao corresponde a um cliente cadastrado.
- Backend persiste `cliente_id` no pedido e usa snapshot oficial de `crm_clients`, nao o texto enviado pela tela.
- Fingerprint de duplicidade passa a considerar `cliente_id` quando disponivel.
- Pedido Direto passa a gravar `cliente_id` no documento final.
- Startup cria indice unico parcial para impedir mais de um SKU ativo por mesma amostra/variacao.
- Adicionados scripts dry-run:
  - `scripts/audit_duplicate_clients.py`
  - `scripts/audit_material_links.py`
  - `scripts/audit_sku_integrity.py`
  - `scripts/audit_order_integrity.py`

## Decisoes bloqueantes e atualizacoes de 2026-08-25

- CGI antes ou depois do SKU: decisao operacional de 2026-08-31 definiu que amostra/variacao aprovada gera SKU imediatamente para autopreencher pedido de venda em negociacao. CGI permanece como gate posterior antes de confirmar o pedido.
- Confirmacao do cliente: hoje existe e-mail em fila e aprovacao manual interna, mas nao ha token publico de confirmacao.
- Papeis de aprovacao comercial do P&D: a permissao atual e ampla e deve ser confirmada antes de restringir.

## Validacao executada

```powershell
python -m pytest backend\tests\test_order_generator_unit.py -q
python -m py_compile scripts\audit_duplicate_clients.py scripts\audit_material_links.py scripts\audit_sku_integrity.py scripts\audit_order_integrity.py
npm run build
python -m py_compile backend\server.py backend\orders_routes.py backend\tests\test_order_generator_unit.py
python -m pytest backend\tests\test_prospect_to_order_sku_unit.py backend\tests\test_sku_governance.py -q
python -m pytest backend\tests\test_contratos_cgi_unit.py backend\tests\test_prospect_to_order_sku_unit.py backend\tests\test_order_generator_unit.py -q
python -m pytest backend\tests\test_pd_pipeline_auto_sync.py -q
python scripts\audit_duplicate_clients.py --limit 5000 --report reports\audit_v2\duplicate_clients_2026-08-24.json
python scripts\audit_sku_integrity.py --limit 5000 --report reports\audit_v2\sku_integrity_2026-08-24.json
python scripts\audit_order_integrity.py --limit 5000 --report reports\audit_v2\order_integrity_2026-08-24.json
python scripts\audit_material_links.py --limit 5000 --report reports\audit_v2\material_links_2026-08-24.json
python scripts\audit_sku_integrity.py --limit 5000 --report reports\audit_v2\sku_integrity_2026-08-25.json
```

Resultados:

- `backend/tests/test_order_generator_unit.py`: 9 passed.
- Scripts de auditoria: compilacao OK.
- Frontend build: compiled successfully.
- Backend alterado: compilacao OK.
- SKU/Prospecto: 1 passed, 2 skipped.
- CGI/SKU/Pedido Direto unitario: 13 passed.
- Sincronizacao CRM/P&D: 13 passed.
- Dry-run clientes: 29 lidos, 1 achado (`duplicate_nome`).
- Dry-run SKUs inicial: 51 lidos, 51 achados (`missing_product_parent_reference`) por leitura da colecao legada `produto_pais`. Em 2026-08-25, o saneamento confirmou que a colecao real e `produtos_pai`; o auditor foi corrigido para ler a fonte certa.
- Dry-run SKUs corrigido em 2026-08-25: 51 SKUs, 17 Produto-Pai, 0 achados.
- Dry-run pedidos: 22 lidos, 23 achados (`manual_item_without_cadastro_pendente_flag`: 15; `order_item_sku_code_missing`: 7; `generator_order_without_cliente_id`: 1).
- Dry-run materiais: 41 itens de estoque lab, 41 achados (`lab_stock_without_material_master`); homologacao e materiais master vazios no banco local.
- Saneamento dry-run 2026-08-25: 67 operacoes planejadas, 0 issues, 0 apply executado. Operacoes: 11 inserts em `materiais`, 15 updates em `orders`, 41 updates em `pd_stock_items`.

## Proxima rodada recomendada

1. Rodar os scripts dry-run contra o Mongo real e anexar os JSON em `reports/audit_v2`.
2. Validar em ambiente integrado a regra DEC-001: amostra/variacao aprovada gera SKU; CGI bloqueia apenas a confirmacao do pedido.
3. Implementar confirmacao externa do cliente, se a decisao for token publico.
4. Endurecer papeis de aprovacao comercial do P&D.
5. Executar teste manual da amostra `2026-1018-a` para retrabalho e aprovacao comercial.
