# PCP DELTA REFRESH 2026-09

Data da auditoria: 2026-09-11

Documento produzido a partir do pedido do usuario para executar apenas PASSO 1 e PASSO 2 do arquivo local
`C:\Users\MARLOS\Downloads\CODEX_MASTER_PROMPT_PCP_DELTA_ONLY.md`.

Este checkpoint distingue instrucoes do documento anexado da solicitacao do usuario: o arquivo foi usado como
especificacao operacional da auditoria DELTA-ONLY, mas nao autoriza alterar codigo funcional antes deste
checkpoint.

## Escopo executado

- PASSO 1: branch de trabalho criada e baseline registrado.
- PASSO 2: refresh da matriz DELTA-ONLY comparando ERP atual com PCP remoto.
- Estrategia: ADD-ONLY / DELTA-ONLY.
- Codigo funcional alterado: nao.
- Implementacao antes do checkpoint: nao.
- Agentes senior usados: 2 auditores read-only.

## Baseline

- Branch atual: `feature/pcp-delta-only-2026-09`.
- Tag local de seguranca: `audit-pre-pcp-delta-20260911-1005`.
- ERP HEAD: `a4b708d50229099dc7bd06902b5e81f2472af198`.
- ERP HEAD data: `2026-09-09 19:03:08 -0300`.
- PCP remoto de referencia: `pcp-kuryos/main`.
- PCP HEAD: `97eb13b018b0d887bb9589ac9ba1b7ede1876ead`.
- PCP HEAD data: `2026-09-11 07:44:32 -0300`.
- `origin` local atual: `https://github.com/DEVMarlosGomes/ERPKuryosBeauty.git`.
- Referencia PCP solicitada pelo usuario: `https://github.com/gcallegaro-kur/PCP-Kuryos`.
- Status no inicio do checkpoint: somente logs locais nao rastreados dos servidores:
  - `backend.err.log`
  - `backend.out.log`
  - `frontend.err.log`
  - `frontend.out.log`

## Fontes lidas

### ERP local

- `docs/PCP_MIGRATION_PLAN.md`
- `docs/PCP_DECISIONS.md`
- `docs/PCP_CONSOLIDATION_MATRIX.md`
- `docs/PCP_DATA_MODEL_MAP.md`
- `docs/PCP_DOMAIN_MAP.md`
- `docs/PCP_LEGACY_NOT_PORTED.md`
- `docs/PCP_SOURCE_INVENTORY.md`
- `docs/PCP_STATUS_MAP.md`
- `docs/AUDITORIA_V2_DECISOES.md`
- `docs/AUDITORIA_V2_RELATORIO_FINAL.md`
- `docs/AUDITORIA_V2_SANEAMENTO_DADOS.md`
- `backend/orders_routes.py`
- `backend/pcp_routes.py`
- `backend/pd_routes.py`
- `backend/crm_routes.py`
- `backend/compras_routes.py`
- `backend/cq_routes.py`
- `backend/estoque_routes.py`
- `backend/recebimento_routes.py`
- `backend/expedicao_routes.py`
- `backend/rbac.py`
- `frontend/src/pages/PCPClonePage.js`
- `frontend/src/pages/PCPProductionPage.js`
- `frontend/src/pages/PCPDailyDashboard.js`
- `frontend/src/pages/SKUsPage.js`
- `frontend/src/pages/PDFormulaBank.js`

### PCP remoto

- `AGENT_STATUS.md`
- `PLANO_PLANEJAMENTO_PCP.md`
- `MELHORIAS_FUTURAS.md`
- `AUDITORIA_INTEGRACAO.md`
- `database.rules.json`
- `storage.rules`
- `functions/index.js`
- `functions/recebimento.js`
- `functions/conferencia_pa.js`
- `public/planejamento.html`
- `public/ops.html`
- `public/separacao_materiais.html`
- `public/descarte.html`
- `public/qualidade.html`
- `public/estoque.html`
- `public/expedicao.html`
- `public/comercial.html`
- paginas RH do legado apenas para classificacao.

## Principio de decisao

Nao portar Firebase, HTML monolitico, watchers, regras de cliente ou fluxos legados quando o ERP possuir
equivalente funcional ou superior. Somente itens abaixo classificados como `MISSING` ou
`PARTIAL_SAFE_EXTEND` podem virar programacao posterior.

## Estado consolidado

### MISSING P0

1. `pcp_allocations` e Pedido -> N OPs por item/saldo.

   O ERP ainda cria uma OP unica por pedido em `/orders/{order_id}/create-op` e grava `order.op_id`. Isso nao
   resolve o alvo de saldo por item, varias OPs por item/SKU e trava para nao planejar quantidade acima do saldo.

   Candidatos:
   - `backend/orders_routes.py`
   - `backend/pcp_routes.py`
   - `frontend/src/pages/OPPage.js`
   - `frontend/src/pages/OPDetail.js`
   - `frontend/src/pages/PCPClonePage.js`
   - `frontend/src/pages/OrdersPage.js`
   - `frontend/src/pages/OrderGeneratorPage.js`

   Colecoes/campos candidatos:
   - `pcp_allocations`
   - `order.items[].id`
   - `order_item_id`
   - `allocation_id`
   - `qtd_planejada`
   - `qtd_produzida`
   - `qtd_confirmada_pcp`
   - `saldo`

2. Separacao guiada FEFO por OP com retorno de falta ao PCP.

   O PCP remoto tem `separacao_materiais.html` com roteiro FEFO e marcacao de separacao concluida na OP. O ERP
   tem WMS, saldos por lote, CQ hard stop e validade, mas nao foi encontrado fluxo equivalente de separacao guiada
   por OP, reserva FEFO e devolucao de falta para replanejamento PCP.

   Candidatos:
   - `backend/estoque_routes.py`
   - `backend/orders_routes.py`
   - `backend/pcp_routes.py`
   - `frontend/src/pages/EstoquePage.js`
   - `frontend/src/pages/PCPProductionPage.js`

   Colecoes/campos candidatos:
   - `wms_separacoes`
   - `production_order_events`
   - `allocation_id`
   - `op_id`
   - `lote`
   - `endereco_id`
   - `validade`
   - `qtd_reservada`
   - `qtd_separada`
   - `faltas[]`

3. Alertas PCP especificos com tolerancia e repique.

   O PCP remoto possui scheduler/alertas para atraso e comunicacao externa, embora parte esteja congelada. No ERP
   ha tarefas e alertas de outros dominios, mas nao foi localizada colecao/worker PCP dedicado para atraso de inicio,
   atraso em producao, estouro de ETA, tolerancias e cooldown.

   Candidatos:
   - `backend/pcp_routes.py`
   - `backend/orders_routes.py`
   - `backend/workflow_engine.py`
   - novo worker/job add-only, se aprovado.

   Colecoes/campos candidatos:
   - `pcp_alerts`
   - `pcp_settings`
   - `tipo`
   - `severidade`
   - `last_sent_at`
   - `cooldown_minutos`
   - `tolerancia_minutos`

### MISSING P1

1. Descarte e logistica reversa dedicada.

   O PCP remoto tem `descarte.html` com fluxo proprio de segregacao, motivo, coleta, destino e baixa apenas na
   confirmacao. O ERP possui movimentacoes/ajustes e disposicoes de CQ/retrabalho, mas nao um fluxo operacional
   proprio para descarte/reversa com trilha completa.

   Candidatos:
   - `backend/estoque_routes.py`
   - `backend/cq_routes.py`
   - `backend/recebimento_routes.py`
   - `frontend/src/pages/EstoquePage.js`

   Colecoes/campos candidatos:
   - `wms_destinacoes`
   - `motivo`
   - `destino`
   - `coleta`
   - `status`
   - `confirmado_por`
   - `confirmado_em`

2. Inventario rotativo e contagem cega WMS.

   O PCP remoto tem contagem cega em `estoque.html`. O ERP tem base WMS, saldos por lote e transferencia, mas nao
   foi encontrado endpoint/tela especifica de inventario rotativo com divergencia e ajuste controlado.

   Candidatos:
   - `backend/estoque_routes.py`
   - `frontend/src/pages/EstoquePage.js`

3. Lote interno e idempotencia completa de recebimento por pedido de compra.

   O PCP remoto evoluiu recebimento para lote interno `AK-AAAA-NNNNNN`, criacao idempotente e integracao com
   qualidade. O ERP recebe em quarentena e cria paletes, mas precisa comparar e, se faltar, estender sem substituir
   o fluxo atual.

   Candidatos:
   - `backend/recebimento_routes.py`
   - `backend/estoque_routes.py`
   - `backend/cq_routes.py`

   Campos candidatos:
   - `lote_interno`
   - `recebimento_key`
   - `pc_id`
   - `item_id`
   - `idempotency_key`
   - `estornado_por`
   - `estornado_em`

4. Defaults fiscais de material.

   NCM, IPI e ICMS-ST quase nao aparecem no modelo atual. O PCP remoto tambem trata isso como pendencia, mas para o
   ERP e um delta add-only util para compras/cadastros.

   Candidatos:
   - `backend/materiais_routes.py`
   - `backend/compras_routes.py`
   - telas de cadastro de materiais/compras.

   Campos candidatos:
   - `ncm`
   - `ipi_default`
   - `icms_st_default`
   - `origem_fiscal`

5. Pacote comercial formal por aprovacao de amostra.

   O ERP ja possui CGI, pedidos, contratos, SKUs, Produto-Pai/BOM e gates comerciais. Ainda nao foi localizada uma
   entidade unica de snapshot do pacote comercial aprovado por amostra com frete, percentual NF, anexos e condicoes.

   Candidatos:
   - `backend/crm_routes.py`
   - `backend/orders_routes.py`
   - `backend/contratos_routes.py`
   - `frontend/src/pages/OrderGeneratorPage.js`

   Colecao candidata:
   - `commercial_packages`

6. Anexos unificados em object storage.

   Ha object storage generico no ERP, mas anexos de pedido usam pasta local `uploads/orders`. A extensao segura e
   unificar metadados e storage sem quebrar downloads atuais.

   Candidatos:
   - `backend/server.py`
   - `backend/orders_routes.py`
   - demais rotas com anexos.

   Colecao candidata:
   - `attachments`

### PARTIAL_SAFE_EXTEND

1. V21 card governance.

   Ha auditoria e imutabilidade em alguns fluxos, e SKU usa inativacao/descontinuacao. Porem ainda existem hard
   deletes em CRM/P&D para projetos, amostras, formulas, testes, documentos e itens relacionados. Extensao segura:
   soft delete, motivo obrigatorio, restore controlado e bloqueio por status sensivel.

   Candidatos:
   - `backend/crm_routes.py`
   - `backend/pd_routes.py`
   - `backend/orders_routes.py`

   Campos candidatos:
   - `deleted_at`
   - `deleted_by`
   - `delete_reason`
   - `restored_at`
   - `restored_by`

2. V21 formula bank e vinculo formula-cliente.

   O banco de formulas existe com RBAC e busca. Produto-Pai/BOM tambem cobre parte do dominio. Falta validar ou
   adicionar, sem duplicar, entidade explicita para multiplos clientes/usos comerciais de uma formula.

   Candidatos:
   - `backend/pd_routes.py`
   - `backend/produtos_routes.py`
   - `frontend/src/pages/PDFormulaBank.js`

   Colecao candidata:
   - `formula_client_links`

3. V21 D48 por politica.

   O gate D48 existe e e centralizado. Falta toggle/politica por tenant ou card, snapshot da regra aplicada e versao
   da politica para auditoria.

   Candidatos:
   - `backend/pd_routes.py`
   - `backend/cadastros_master_routes.py`
   - telas de configuracao.

   Campos candidatos:
   - `tenant_settings.pd.require_d48`
   - `d48_required_snapshot`
   - `d48_policy_version`

4. Planejamento PCP, timeline e setup.

   O ERP ja possui linhas, calendario, slots, programacao, sugestao de setup e apontamentos. A extensao segura deve
   focar no que falta: timeline por item/saldo, setup real/eventos, auditoria de movimentacao e consistencia de
   status alvo.

   Candidatos:
   - `backend/pcp_routes.py`
   - `backend/orders_routes.py`
   - `frontend/src/pages/PCPClonePage.js`
   - `frontend/src/pages/PCPProductionPage.js`

5. ETA com paradas.

   O ERP registra pausas e apontamentos e calcula dados de producao. Falta ETA produtivo confiavel considerando
   paradas, setup e ritmo recente, alem de exibicao operacional e alerta quando estourar.

   Candidatos:
   - `backend/orders_routes.py`
   - `backend/pcp_routes.py`
   - `frontend/src/pages/PCPProductionPage.js`
   - `frontend/src/pages/PCPDailyDashboard.js`

6. Fechamento do dia e KPIs.

   O ERP tem dashboard PCP, historico e dados de apontamento. Ainda nao apareceu `day_closings` com fechamento
   controlado, snapshot de metas, perdas, paradas, setup e reconciliacao do dia.

   Candidatos:
   - `backend/pcp_routes.py`
   - `frontend/src/pages/PCPDailyDashboard.js`

   Colecao candidata:
   - `day_closings`

7. Qualidade de fornecedor em cotacao.

   O ERP tem fornecedor homologado, RNC, reavaliacao e hard stop. Falta confirmar se a tela/comparador de cotacao
   mostra nota/selo/risco de qualidade na decisao de compra.

   Candidatos:
   - `backend/compras_routes.py`
   - `frontend/src/pages/ComprasCotacao.js`
   - `frontend/src/pages/ComprasFornecedorDetalhe.js`

8. Quarentena fisica WMS.

   O ERP ja possui status CQ e bloqueios. Falta validar se existe area/endereco fisico configuravel de quarentena,
   distinta de apenas status logico.

   Candidatos:
   - `backend/estoque_routes.py`
   - `backend/cq_routes.py`
   - telas WMS/estoque.

9. Comercial, expedicao parcial e saldo produzido.

   O ERP tem pedidos, expedição, CQ hard stop, romaneio, baixa de estoque e contratos. Falta comparar se entrega
   parcial, percentual NF, CIF/FOB, aditivo/cancelamento e saldo produzido por item de pedido estao todos
   preservados como snapshot operacional.

   Candidatos:
   - `backend/orders_routes.py`
   - `backend/expedicao_routes.py`
   - `backend/contratos_routes.py`
   - `frontend/src/pages/ExpedicaoPage.js`
   - `frontend/src/pages/OrdersPage.js`

### EQUIVALENT_EXISTS

1. Importacao semanal PCP.

   O ERP ja neutralizou importacao semanal com retorno `410`. Nao portar UI/fluxo de importacao legado.

2. Status de confirmacao PCP final.

   O ERP possui status `aguardando_confirmacao_pcp` e exige confirmacao PCP para finalizar OP. O slot concluido no
   PCP deve levar OP para aguardando confirmacao, nao para final automatico.

3. CQ operacional.

   O ERP tem RA, RNC, retencao, checklists, instrumentos, CoA, concessao/reprovacao e hard stops em estoque e
   expedicao. Nao portar `qualidade.html` como modulo paralelo.

4. WMS base.

   O ERP tem enderecos, saldos por lote, movimentacoes, transferencia e bloqueios CQ. Portar apenas gaps add-only:
   separacao guiada, inventario rotativo e quarentena fisica se faltarem.

5. Compras/MRP base.

   O ERP ja tem MRP, revisao/aprovacao e geracao de demandas de compra. Nao copiar a matriz do PCP sem provar delta.

6. SKU base.

   O ERP ja tem SKU gerado por variacao aprovada, idempotencia e descontinuacao/inativacao. Extender apenas governanca
   manual/auditoria se faltar.

### ERP_SUPERIOR

1. CQ/WMS integrado e bloqueios por lote/palete.

   Superior ao `qualidade.html` do PCP remoto.

2. Produto-Pai/BOM versionado.

   Superior a uma formula solta do legado para separar granel, embalagem, cliente e SKU.

3. CGI, contratos e gates comerciais.

   Superior ao fluxo comercial HTML do PCP para validacoes juridico-comerciais, desde que o snapshot operacional
   seja fechado onde faltar.

### LEGACY_ONLY

- Firebase Realtime Database.
- `database.rules.json`.
- `storage.rules`.
- `auth_check.js`.
- HTML monolitico em `public/*.html`.
- Watchers e mutacoes em page-load.
- Auto-conclusao por 95%.
- UI `horizonte.html`.
- Importacao semanal.
- Scripts `.DEPRECATED`.

### BUG_DO_LEGADO

- Auto-conclusao por 95% sem confirmacao PCP.
- Mutacoes invisiveis em page-load.
- `admin.html` com escrita ampla em configuracao.
- Runtime Node.js 20 do Firebase com deprecacao operacional antes de 2026-10-30.
- Inconsistencias de turno/e-mail citadas em `MELHORIAS_FUTURAS.md`.

### BLOCKED_BY_DECISION

- RH legado continua fora do PCP/ERP ate decisao explicita.
- Override para produzir sem confirmacao externa do cliente ainda depende de decisao.
- Papel comercial final para aprovar pendencias sensiveis ainda deve ser fechado com negocio.

### BLOCKED_BY_PROCESS

- Apontamento de manipulacao/OM depende disciplina de pesagem e processo operacional.
- Estoque real/endereco confiavel depende Dia D de estoque para uso forte em MRP e separacao.
- Hard lock de alocacao de OP deve aguardar definicao de tolerancias e regras de excecao.

## Feature flags candidatas

- `pcp_quantity_planning_v2`
- `pcp_op_timeline_v2`
- `pcp_material_picking_v2`
- `pcp_disposal_v2`
- `pcp_alerts_enabled`
- `pcp_supplier_quality_quote_v2`
- `material_tax_defaults_v2`
- `shared_attachments_v2`
- `v21_card_governance`
- `v21_formula_links`
- `v21_d48_policy`
- `v21_commercial_package`
- `v21_sku_crud_governance`

## Indices candidatos

- `pcp_allocations(tenant_id, order_id, item_id)`
- `pcp_allocations(tenant_id, sku_id, status)`
- `pcp_allocations(tenant_id, allocation_id)`
- `production_orders(tenant_id, order_id, order_item_id, status)`
- `production_order_events(tenant_id, op_id, created_at)`
- `pcp_alerts(tenant_id, status, severidade)`
- `pcp_alerts(tenant_id, tipo, last_sent_at)`
- `day_closings(tenant_id, data, linha_id)`
- `wms_separacoes(tenant_id, op_id, status)`
- `wms_separacoes(tenant_id, endereco_id, lote)`
- `formula_client_links(tenant_id, formula_id, client_id)`
- `attachments(tenant_id, owner_type, owner_id)`

## Riscos principais

1. Duplicar fonte de verdade entre pedido, OP, programacao, estoque e MRP.
2. Produzir sem lastro por item de pedido por causa da OP unica por pedido.
3. Hard deletes em CRM/P&D contra governanca V21.
4. KPI/fechamento derivados de dados incompletos.
5. D48 sem snapshot da politica aplicada.
6. Papeis amplos demais para confirmacao PCP.
7. Anexos de pedido fora do storage unificado.

## Rollback add-only

- Desligar feature flags.
- Esconder rotas/telas novas sem remover dados.
- Manter colecoes novas como historico/auditoria, sem tocar colecoes antigas.
- Parar workers/jobs antes de qualquer limpeza.
- Nao alterar status, endpoints ou fluxos atuais sem fase posterior aprovada.

## PCP DELTA CHECKPOINT

### Arquivos candidatos para implementacao posterior

Backend:
- `backend/orders_routes.py`
- `backend/pcp_routes.py`
- `backend/estoque_routes.py`
- `backend/recebimento_routes.py`
- `backend/expedicao_routes.py`
- `backend/compras_routes.py`
- `backend/cq_routes.py`
- `backend/pd_routes.py`
- `backend/crm_routes.py`
- `backend/produtos_routes.py`
- `backend/cadastros_master_routes.py`
- `backend/rbac.py`
- `backend/workflow_engine.py`
- `backend/server.py`

Frontend:
- `frontend/src/pages/PCPClonePage.js`
- `frontend/src/pages/PCPProductionPage.js`
- `frontend/src/pages/PCPDailyDashboard.js`
- `frontend/src/pages/OPPage.js`
- `frontend/src/pages/OPDetail.js`
- `frontend/src/pages/OrdersPage.js`
- `frontend/src/pages/OrderGeneratorPage.js`
- `frontend/src/pages/EstoquePage.js`
- `frontend/src/pages/RecebimentoPage.js`
- `frontend/src/pages/ExpedicaoPage.js`
- `frontend/src/pages/ComprasCotacao.js`
- `frontend/src/pages/ComprasFornecedorDetalhe.js`
- `frontend/src/pages/SKUsPage.js`
- `frontend/src/pages/PDFormulaBank.js`

### Itens autorizaveis para programacao posterior

Somente estes blocos estao elegiveis para proximo passo tecnico:

- `MISSING P0`: `pcp_allocations` e Pedido -> N OPs por item/saldo.
- `MISSING P0`: separacao guiada FEFO por OP.
- `MISSING P0`: alertas PCP especificos com tolerancia e repique.
- `MISSING P1`: descarte/logistica reversa dedicada.
- `MISSING P1`: inventario rotativo/contagem cega WMS.
- `MISSING P1`: lote interno/idempotencia de recebimento, apenas se o ERP nao possuir equivalente ao comparar mais fundo.
- `MISSING P1`: defaults fiscais de material.
- `MISSING P1`: pacote comercial formal, apenas como snapshot add-only.
- `MISSING P1`: anexos unificados em object storage.
- `PARTIAL_SAFE_EXTEND`: V21 card governance.
- `PARTIAL_SAFE_EXTEND`: V21 formula-client links.
- `PARTIAL_SAFE_EXTEND`: V21 D48 policy/snapshot.
- `PARTIAL_SAFE_EXTEND`: timeline/setup/ETA/fechamento/KPIs PCP.
- `PARTIAL_SAFE_EXTEND`: qualidade fornecedor em cotacao.
- `PARTIAL_SAFE_EXTEND`: quarentena fisica WMS.
- `PARTIAL_SAFE_EXTEND`: comercial/expedicao parcial/saldo produzido.

### Itens explicitamente nao autorizados para portar

- Firebase, rules, storage rules e auth frontend do legado.
- HTML monolitico do PCP remoto.
- Auto-conclusao por 95%.
- Importacao semanal.
- RH legado.
- Qualidade completa do legado, pois o ERP e superior.
- MRP/compras do legado, salvo delta provado contra o ERP.
- WMS base do legado, salvo separacao/inventario/quarentena fisica se ausentes.

### Proxima ordem recomendada

1. Lote 0 read-only: confirmar schemas reais de `orders`, `ops`, `pcp_programacao`, `estoque_saldos_lote` e `compras_mrp_rodadas` em ambiente de dados.
2. Lote 1 add-only: `pcp_allocations` + Pedido item -> N OPs, sem remover `order.op_id`.
3. Lote 2 add-only: separacao FEFO por OP com feature flag.
4. Lote 3 add-only: alertas PCP e fechamento/KPIs.
5. Lote 4 add-only: governanca V21 e D48 policy/snapshot.

