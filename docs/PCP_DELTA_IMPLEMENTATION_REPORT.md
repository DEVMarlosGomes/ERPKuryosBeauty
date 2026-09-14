# PCP DELTA IMPLEMENTATION REPORT

Data: 2026-09-11

## Slice 1 - `pcp_quantity_planning_v2`

Classificacao do checkpoint: `MISSING P0`.

Objetivo: adicionar a primeira camada add-only de planejamento por quantidade para permitir Pedido -> N OPs por
item/saldo sem remover o fluxo antigo de OP unica por pedido.

## O que foi adicionado

- Campo opcional `OrderItem.id` para novos itens de pedido.
- Backfill add-only de `items[].id` quando uma rota v2 de alocacao PCP encontra item legado sem ID.
- Feature flag `pcp_quantity_planning_v2`, lida de `tenant_settings.features`.
- Nova colecao logica `pcp_allocations`.
- Nova colecao logica `production_order_events` para trilha minima de criacao de OP por alocacao.
- Rota para listar alocacoes do pedido.
- Rota para criar alocacao por item de pedido.
- Rota para criar OP a partir de uma alocacao.
- Testes unitarios do fluxo de flag, saldo e consumo parcial da alocacao.
- Tela React `PCPQuantityPlanningPage` em `/pcp/planejamento/quantidades`.
- Entrada add-only no menu PCP para `Quantidades`.

## Preservado

- Endpoint antigo `POST /api/orders/{order_id}/create-op`.
- Campo antigo `order.op_id`.
- Status existentes de pedido e OP.
- Tela atual de PCP/OP.
- Collections existentes `orders` e `ops`.

## Regras implementadas

- Feature nova nasce desligada.
- Pedido precisa estar `confirmado` ou `em_producao`.
- Alocacao nao pode exceder saldo do item sem override.
- OP v2 nao pode exceder saldo da alocacao sem override.
- Override exige `admin` e `override_reason`.
- OP criada pela trilha v2 recebe `allocation_id` e `sales_order_item_id`.
- Criacao de OP v2 atualiza consumo/restante da alocacao.
- Primeira OP v2 ainda preenche `order.op_id` quando vazio, para compatibilidade com telas antigas.
- Revisao tecnica da OP v2 avalia apenas o item vinculado a alocacao.

## Testes

- `pytest backend/tests/test_pcp_allocations_unit.py backend/tests/test_order_generator_unit.py backend/tests/test_pcp_routes_unit.py`
  - Resultado: `22 passed`.
- `pytest backend/tests`
  - Resultado: `91 passed, 278 skipped`.
- `npm run build` em `frontend` com `DISABLE_ESLINT_PLUGIN=true` e `GENERATE_SOURCEMAP=false`
  - Resultado: `Compiled successfully`.

## Estado

GO COM RESSALVAS para o backend do Slice 1.

Ressalvas:
- Ainda nao ha indices Mongo criados por migration/dry-run.
- Ainda nao ha endpoint de cancelamento/restauracao de alocacao.
- Ainda nao ha concorrencia transacional forte para dois usuarios criando OP simultaneamente.

## Slice 2 - UI Planejamento > Quantidades

Classificacao do checkpoint: `MISSING P0`.

Objetivo: disponibilizar uma primeira tela operacional para consumir as rotas v2 de alocacao sem substituir o
Planejamento PCP atual.

## O que foi adicionado

- Lazy route `/pcp/planejamento/quantidades`.
- Item de sidebar `Quantidades` dentro do grupo PCP.
- Selecao de pedidos, busca e filtro de pedidos encerrados.
- Visao por item de pedido com quantidade do pedido, planejado, saldo e quantidade em OPs.
- Dialogo para criar alocacao por item.
- Dialogo para gerar OP a partir da alocacao.
- Estado de feature flag desligada tratado como bloqueio operacional, sem quebrar a tela.

## Preservado

- `/pcp/planejamento` segue apontando para `PCPClonePage`.
- `/pcp/horizonte`, `/pcp/controle-ops`, `/pcp/emitir-op` e apontamento seguem intactos.

## Slice 3 - Separacao FEFO backend

Classificacao do checkpoint: `MISSING P0`.

Objetivo: adicionar uma primeira API backend para separacao guiada FEFO por OP, usando OP, BOM, Estoque/WMS e CQ
existentes, sem criar estoque paralelo e sem baixa destrutiva neste slice.

## O que foi adicionado

- Feature flag `pcp_material_picking_v2`, lida de `tenant_settings.features`.
- Rotas novas de sugestao e confirmacao de separacao por OP.
- Resolucao de necessidades por BOM vigente de Produto-Pai/SKU.
- Filtro de lotes sem saldo, quarentena, reprovados, bloqueados, segregados, inativos e enderecos WMS bloqueados.
- Ordenacao FEFO por validade, lote e endereco.
- Confirmacao idempotente em `wms_separacoes`.
- Evento `confirm_wms_picking` em `production_order_events`.
- Atualizacao add-only da OP com `wms_separacao_id` e `wms_separacao_status`.

## Preservado

- Nenhuma baixa de estoque automatica.
- Nenhuma substituicao dos endpoints WMS existentes.
- Nenhuma alteracao de status atual de OP.

## Ressalvas

- Ainda falta tela React para separacao FEFO.
- Ainda falta movimento WMS fisico seguro para reservar/baixar materiais.
- Ainda falta controle transacional forte para concorrencia em separacao simultanea.

## Slice 4 - UI Separacao FEFO no Detalhe da OP

Classificacao do checkpoint: `MISSING P0`.

Objetivo: expor a sugestao/confirmacao de separacao FEFO no fluxo atual de OP, sem criar nova tela paralela de
estoque e sem alterar o apontamento de producao.

## O que foi adicionado

- Painel `Separacao FEFO / WMS` em `OPDetail`.
- Carregamento da sugestao `GET /api/ops/{op_id}/material-picking/suggestion`.
- Tratamento visual de feature flag desligada.
- Resumo de materiais, faltas, movimento sem baixa e status de separacao da OP.
- Tabela de materiais com necessario, disponivel, falta e linhas FEFO por lote/endereco/validade.
- Confirmacao idempotente via `POST /api/ops/{op_id}/material-picking/confirm`.

## Preservado

- Apontamentos, pausas, perdas e confirmacao PCP continuam no mesmo fluxo.
- A confirmacao FEFO nao baixa estoque automaticamente.
- A tela de Producao continua apontando para `OPDetail`.

## Testes atualizados

- `pytest backend/tests`
  - Resultado: `91 passed, 278 skipped`.
- `npm run build` em `frontend` com `DISABLE_ESLINT_PLUGIN=true` e `GENERATE_SOURCEMAP=false`
  - Resultado: `Compiled successfully`.

## Slice 5 - Alertas PCP backend

Classificacao do checkpoint: `MISSING P0`.

Objetivo: adicionar a primeira API add-only de alertas PCP para inicio atrasado e OP em andamento estourada, com
tolerancia e repique, sem envio externo automatico neste slice.

## O que foi adicionado

- Feature flag `pcp_alerts_enabled`, lida de `tenant_settings.features`.
- Nova colecao logica `pcp_alerts`.
- Rota para listar alertas PCP.
- Rota para executar check manual/dry-run de alertas.
- Rota para resolver alertas.
- Regras de tolerancia em minutos, default 5.
- Regras de cooldown/repique em minutos, default 10.
- Idempotencia por `alert_key` enquanto o alerta estiver aberto/pendente.
- Campo `notificacao_externa_enviada=false` para explicitar que este slice nao dispara canal externo.

## Preservado

- Fluxo de programacao PCP, transicoes de slot e status de OP.
- Scheduler global e notificacoes existentes.
- Nenhum alerta e criado quando a feature flag esta desligada.

## Testes atualizados

- `pytest backend/tests/test_pcp_alerts_unit.py backend/tests/test_pcp_routes_unit.py`
  - Resultado: `9 passed`.
- `pytest backend/tests`
  - Resultado: `95 passed, 278 skipped`.

## Slice 6 - Inventario ciclico WMS backend

Classificacao do checkpoint: `MISSING P1`.

Objetivo: adicionar contagem cega/rotativa WMS sobre `estoque_saldos_lote`, com snapshot, divergencia e ajuste
controlado pelo kardex existente.

## O que foi adicionado

- Feature flag `wms_cycle_count_v2`, lida de `tenant_settings.features`.
- Nova colecao logica `wms_inventarios_ciclicos`.
- Rota para listar inventarios ciclicos.
- Rota para abrir inventario a partir dos saldos atuais por lote/endereco.
- Rota para obter inventario com modo cego por padrao e `reveal_system` opcional.
- Rota para registrar contagens por `saldo_lote_id`.
- Rota para fechar inventario com ou sem aplicacao de ajuste.
- Bloqueio de ajuste quando o saldo atual diverge do snapshot, evitando sobrescrever movimentacao concorrente.

## Preservado

- `estoque_saldos_lote` continua sendo a fonte de saldo WMS.
- Ajustes, quando aplicados, reutilizam `POST /api/estoque/wms/saldos/ajustar` e geram `estoque_movimentos_lote`.
- Nenhuma baixa/ajuste ocorre durante abertura ou registro de contagem.

## Testes atualizados

- `pytest backend/tests/test_wms_recebimento_unit.py`
  - Resultado: `6 passed`.
- `pytest backend/tests`
  - Resultado: `98 passed, 278 skipped`.
- `npm run build` em `frontend` com `DISABLE_ESLINT_PLUGIN=true` e `GENERATE_SOURCEMAP=false`
  - Resultado: `Compiled successfully`.

## Slice 7 - Descarte e logistica reversa WMS backend

Classificacao do checkpoint: `MISSING P1`.

Objetivo: adicionar fluxo dedicado de destinacao WMS para descarte, devolucao ao fornecedor/logistica reversa e
reprocesso, preservando o estoque como fonte unica e aplicando baixa somente na confirmacao.

## O que foi adicionado

- Feature flag `pcp_disposal_v2`, lida de `tenant_settings.features`.
- Nova colecao logica `wms_destinacoes`.
- Rota para listar destinacoes.
- Rota para criar destinacao por `saldo_lote_id`.
- Rota para programar coleta.
- Rota para confirmar destinacao e aplicar baixa WMS.
- Rota para cancelar destinacao antes da confirmacao.
- Bloqueio de excesso considerando saldo atual e destinacoes abertas para o mesmo saldo.
- Confirmacao idempotente quando a destinacao ja esta confirmada.

## Preservado

- `estoque_saldos_lote` continua sendo a fonte de saldo.
- A baixa reaproveita `POST /api/estoque/wms/saldos/ajustar` em modo `saida`.
- O kardex `estoque_movimentos_lote` segue como trilha imutavel.
- Criacao e programacao de coleta nao alteram estoque.

## Testes atualizados

- `pytest backend/tests/test_wms_recebimento_unit.py`
  - Resultado: `9 passed`.
- `pytest backend/tests`
  - Resultado: `101 passed, 278 skipped`.
- `npm run build` em `frontend` com `DISABLE_ESLINT_PLUGIN=true` e `GENERATE_SOURCEMAP=false`
  - Resultado: `Compiled successfully`.

## Slice 8 - Lote interno e idempotencia de recebimento backend

Classificacao do checkpoint: `MISSING P1`.

Objetivo: estender o recebimento granular existente com chave idempotente e lote interno estavel, sem substituir o
fluxo atual de entrada, CQ, paletes, PO e WMS.

## O que foi adicionado

- Feature flag `receiving_internal_lot_v2`, lida de `tenant_settings.features`.
- Campo opcional `idempotency_key` no recebimento.
- Campo opcional `lote_interno` por item recebido.
- Calculo de `recebimento_key` quando a flag esta ligada.
- Replay idempotente antes de qualquer efeito colateral quando a mesma chave ja foi processada.
- Geracao automatica de lote interno no padrao `AK-AAAA-NNNNNN`.
- Propagacao de `lote_interno` para recebimento, RA/CQ, saldo WMS, paletes, movimento de estoque e PO.
- Indices candidatos/sparse para `recebimento_key` e `idempotency_key`.

## Preservado

- `POST /api/recebimento/entradas` continua sendo o endpoint de entrada.
- Quando a flag esta desligada, o fluxo antigo permanece sem exigir novos campos.
- Recebimento segue imutavel e sem DELETE.
- Itens continuam entrando em quarentena CQ.

## Testes atualizados

- `pytest backend/tests/test_wms_recebimento_unit.py`
  - Resultado: `10 passed`.
- `pytest backend/tests`
  - Resultado: `102 passed, 278 skipped`.
- `npm run build` em `frontend` com `DISABLE_ESLINT_PLUGIN=true` e `GENERATE_SOURCEMAP=false`
  - Resultado: `Compiled successfully`.

## Slice 9 - Defaults fiscais de material backend

Classificacao do checkpoint: `MISSING P1`.

Objetivo: adicionar defaults fiscais opcionais no cadastro de materiais comprados, sem alterar contratos de compra,
PO, recebimento ou faturamento.

## O que foi adicionado

- Feature flag `material_tax_defaults_v2`, lida de `tenant_settings.features`.
- Modelo opcional `MaterialFiscalDefaults`.
- Campo opcional `fiscal_defaults` em criacao/atualizacao de material.
- Rota add-only `PATCH /api/cadastros/materiais/{codigo_interno}/fiscal-defaults`.
- Campos opcionais `ncm`, `cest`, `ipi_default`, `icms_st_default`, `origem_fiscal` e `observacoes_fiscais`.
- Normalizacao de NCM/CEST para digitos.
- Validacao de NCM com 8 digitos, CEST com 7 digitos, percentuais entre 0 e 100 e origem fiscal 0-8.
- Auditoria leve de atualizacao fiscal por usuario/data.
- Indice candidato `materiais(tenant_id, ncm)`.

## Preservado

- Criacao de material sem fiscal continua funcionando com a feature desligada.
- Compras, PO e recebimento nao passam a exigir dados fiscais.
- Nenhum calculo fiscal automatico foi introduzido.

## Testes atualizados

- `pytest backend/tests/test_materiais_fiscal_defaults_unit.py backend/tests/test_wms_recebimento_unit.py`
  - Resultado: `14 passed`.
- `pytest backend/tests`
  - Resultado: `106 passed, 278 skipped`.
- `npm run build` em `frontend` com `DISABLE_ESLINT_PLUGIN=true` e `GENERATE_SOURCEMAP=false`
  - Resultado: `Compiled successfully`.

## Slice 10 - Pacote comercial por aprovacao de amostra backend

Classificacao do checkpoint: `MISSING P1`.

Objetivo: criar um snapshot comercial formal por variacao aprovada pelo cliente, sem substituir pedido, SKU, Kickoff,
CGI/contrato ou anexos atuais.

## O que foi adicionado

- Feature flag `v21_commercial_package`, lida de `tenant_settings.features`.
- Nova colecao `commercial_packages`.
- Rota add-only `GET /api/crm/samples/{sample_id}/variacoes/{variacao_id}/commercial-packages`.
- Rota add-only `POST /api/crm/samples/{sample_id}/variacoes/{variacao_id}/commercial-packages`.
- Snapshot versionado com amostra, variacao, projeto, cliente, SKU, frete, condicoes, percentual NF e anexos.
- Validacao de variacao aprovada pelo cliente antes de criar o pacote.
- Validacao de `percentual_nf` entre 0 e 100, `condicao_pagamento` no padrao `NNN/NNN/NNN`, frete/preco/prazo nao negativos.
- Replay idempotente por `idempotency_key` opcional.
- Indices candidatos para consulta por amostra/variacao e idempotencia.
- Auditoria `commercial_package_created`.

## Preservado

- `resultado-cliente` continua sendo o ponto de aprovacao da amostra/variacao.
- Criacao de SKU existente nao foi alterada.
- Pedidos, Kickoff, CGI/contratos e anexos de pedido nao passam a depender do pacote.
- O novo pacote e historico/snapshot, nao fonte transacional unica.

## Testes atualizados

- `pytest backend/tests/test_commercial_packages_unit.py`
  - Resultado: `5 passed`.
- `pytest backend/tests`
  - Resultado: `111 passed, 278 skipped`.
- `npm run build` em `frontend` com `DISABLE_ESLINT_PLUGIN=true` e `GENERATE_SOURCEMAP=false`
  - Resultado: `Compiled successfully`.

## Slice 11 - Anexos unificados em object storage

Classificacao do checkpoint: `MISSING P1`.

Objetivo: criar uma camada unificada de metadados/vinculo de anexos em `attachments`, reaproveitando o object storage
generico existente e preservando os anexos/downloads locais de pedido.

## O que foi adicionado

- Feature flag `unified_attachments_v2`, lida de `tenant_settings.features`.
- Nova colecao/indice `attachments` para metadados unificados.
- Aliases `owner_type/owner_id` e `entity_type/entity_id` para facilitar uso por fluxos antigos e novos.
- Extensao add-only de `POST /api/upload` com parametros opcionais `owner_type`, `owner_id` e `relation`.
- Nova rota `GET /api/attachments` para listar anexos por owner/entity.
- Nova rota `GET /api/attachments/{attachment_id}/download` para baixar anexos vinculados ao object storage.
- Extensao add-only de `POST /api/orders/{order_id}/attachments` para tentar object storage e espelhar metadados em
  `attachments` quando a flag esta ligada.
- Fallback local automatico para anexos de pedido quando object storage nao esta disponivel.
- Nova rota `GET /api/orders/{order_id}/attachments/metadata` para expor metadados unificados, com fallback para
  `orders.attachments` legado.

## Preservado

- `GET /api/orders/{order_id}/attachments` continua retornando a lista embutida do pedido.
- `GET /api/orders/{order_id}/attachments/{attachment_id}/download` continua servindo anexos locais antigos.
- `/api/upload` sem `owner_type/owner_id` preserva o contrato antigo e grava apenas em `files`.
- Nenhum fluxo de CRM, Kickoff, CQ, proposta ou pedido passa a exigir `attachments`.

## Testes atualizados

- `pytest backend/tests/test_order_generator_unit.py backend/tests/test_unified_attachments_unit.py`
  - Resultado: `16 passed`.
- `pytest backend/tests`
  - Resultado: `116 passed, 278 skipped`.
- `npm run build` em `frontend` com `DISABLE_ESLINT_PLUGIN=true` e `GENERATE_SOURCEMAP=false`
  - Resultado: `Compiled successfully`.

## Slice 12 - V21 card governance backend inicial

Classificacao do checkpoint: `PARTIAL_SAFE_EXTEND`.

Objetivo: adicionar caminhos governados de arquivamento/restauracao com motivo obrigatorio e bloqueio por status
sensivel, sem remover nem alterar os DELETEs atuais.

## O que foi adicionado

- Feature flag `v21_card_governance`, lida de `tenant_settings.features`.
- Rotas add-only em CRM para arquivar/restaurar projetos, amostras e variacoes.
- Rotas add-only em P&D para arquivar/restaurar solicitacoes P&D.
- Campos opcionais `is_deleted`, `deleted_at`, `deleted_by`, `deleted_by_name`, `delete_reason`, `restored_at`,
  `restored_by`, `restored_by_name` e `restore_reason`.
- Motivo obrigatorio com pelo menos 5 caracteres.
- Bloqueio de projeto com SKU/amostra aprovada.
- Bloqueio de amostra/variacao aprovada, com aprovacao externa ou SKU.
- Bloqueio de solicitacao P&D em `APPROVED` ou `COMPLETED`.
- Propagacao do soft archive/restore para `pd_cards` vinculados a `pd_requests`.
- Auditoria via `audit_log` para archive/restore.
- Indices candidatos por `is_deleted` em `crm_projects`, `crm_samples` e `pd_requests`.

## Preservado

- DELETEs existentes continuam registrados e sem mudanca de contrato nesta fase.
- Listagens atuais nao foram filtradas automaticamente por `is_deleted`.
- Status, transicoes e fluxos de aprovacao continuam iguais.
- Nenhuma cascata destrutiva foi substituida nesta etapa.

## Testes atualizados

- `pytest backend/tests/test_card_governance_unit.py`
  - Resultado: `5 passed`.
- `pytest backend/tests`
  - Resultado: `121 passed, 278 skipped`.
- `npm run build` em `frontend` com `DISABLE_ESLINT_PLUGIN=true` e `GENERATE_SOURCEMAP=false`
  - Resultado: `Compiled successfully`.

## Slice 13 - V21 formula bank e vinculo formula-cliente

Classificacao do checkpoint: `PARTIAL_SAFE_EXTEND`.

Objetivo: adicionar entidade explicita para vincular uma formula existente a multiplos clientes/usos comerciais, sem
duplicar Produto-Pai/BOM e sem alterar o banco de formulas atual.

## O que foi adicionado

- Feature flag `formula_client_links_v2`, lida de `tenant_settings.features`.
- Nova colecao `formula_client_links`.
- Rota add-only `GET /api/pd/formulas/{formula_id}/client-links`.
- Rota add-only `POST /api/pd/formulas/{formula_id}/client-links`.
- Rota add-only `PUT /api/pd/formulas/{formula_id}/client-links/{link_id}`.
- Validacao de formula, cliente, projeto, SKU e Produto-Pai por tenant.
- Reuso idempotente por `idempotency_key`.
- Reuso de vinculo ativo existente por formula/cliente/uso comercial.
- Snapshot leve de formula e solicitacao P&D de origem.
- Vinculo novo nasce `ativo` apenas para formula registrada, bloqueada e aprovada internamente/pelo cliente.
- Formula ainda nao registrada gera vinculo `em_validacao`.
- Inativacao governada com motivo obrigatorio.
- Reativacao bloqueia duplicidade de formula/cliente/uso e limpa campos antigos de inativacao.
- Auditoria `formula_client_link_created` e `formula_client_link_updated`.
- Indices candidatos por formula, cliente e idempotencia.
- Indice unico parcial para evitar corrida concorrente de vinculos `ativo`/`em_validacao`.

## Preservado

- `GET /api/pd/formulas/bank` continua inalterado.
- Formula, itens de formula, Produto-Pai, BOM e SKU nao passam a depender do novo vinculo.
- Importacao, duplicacao e versionamento de formula continuam iguais.

## Testes atualizados

- `pytest backend/tests/test_formula_client_links_unit.py`
  - Resultado: `13 passed`.
- `pytest backend/tests`
  - Resultado: `134 passed, 278 skipped`.
- `npm run build` em `frontend` com `DISABLE_ESLINT_PLUGIN=true` e `GENERATE_SOURCEMAP=false`
  - Resultado: `Compiled successfully`.

## Slice 14 - V21 D48 por politica

Classificacao do checkpoint: `PARTIAL_SAFE_EXTEND`.

Objetivo: tornar o gate D48 configuravel por tenant ou por card/requisicao, preservando a exigencia padrao atual e
gravando snapshot auditavel da regra aplicada.

## O que foi adicionado

- Politica tenant-level em `tenant_settings.pd.require_d48`.
- Versionamento em `tenant_settings.pd.d48_policy_version` e `tenant_settings.pd.d48_policy`.
- Rota add-only `GET /api/pd/settings/d48-policy`.
- Rota add-only `PUT /api/pd/settings/d48-policy`.
- Rota add-only `PUT /api/pd/requests/{req_id}/d48-policy`.
- Override opcional por requisicao/card via `d48_required_override`.
- Snapshot `d48_required_snapshot` no gate aplicado.
- Campos `d48_policy_version`, `d48_policy_source`, `d48_gate_checked_at`, `d48_gate_satisfied_at` e
  `d48_gate_skipped_at`.
- Auditoria `d48_policy_updated` e `d48_request_policy_updated`.

## Preservado

- Sem configuracao explicita, D48 continua obrigatorio.
- As leituras continuam vindo de `pd_stability_studies`.
- Os tres caminhos existentes continuam usando o mesmo ponto de verdade:
  `transition_status`, envio de amostra e Kanban/card.
- Nenhum status ou fluxo comercial existente foi removido.

## Testes atualizados

- `pytest backend/tests/test_pd_pipeline_auto_sync.py`
  - Resultado: `17 passed`.
- `pytest backend/tests`
  - Resultado: `140 passed, 278 skipped`.

## Slice 15 - PCP timeline, setup real, ETA e fechamento diario

Classificacao do checkpoint: `MISSING`.

Objetivo: validar a camada add-only para eventos operacionais de timeline, timeline consolidada por OP/item/alocacao,
ETA operacional e fechamento diario com KPIs/reconciliacao, sem alterar status, endpoints ou telas existentes.

## O que foi coberto

- Feature flag `pcp_timeline_eta_v2`, lida de `tenant_settings.features`.
- Rota add-only `POST /api/pcp/ops/{op_id}/timeline-events`.
- Rota add-only `GET /api/pcp/ops/{op_id}/timeline`.
- Rota add-only `GET /api/pcp/ops/{op_id}/eta`.
- Rota add-only `GET /api/pcp/day-closings`.
- Rota add-only `POST /api/pcp/day-closings`.
- Registro idempotente de evento real de setup em `production_order_events`.
- Timeline agregando OP, item comercial, alocacao PCP, slots, eventos, apontamentos, perdas, pausas e separacao WMS.
- ETA considerando quantidade planejada/produzida, ritmo recente, pausas e setup.
- Fechamento diario como snapshot com KPIs, perdas, paradas, setup e reconciliacao.

## Preservado

- Status de OP, slot, lote e pedido nao sao alterados por criar evento de timeline.
- `ops.apontamentos`, `ops.perdas` e `ops.pausas` continuam sendo fontes operacionais existentes.
- `pcp_programacao`, `historico`, WMS e confirmacao PCP continuam com seus contratos atuais.
- Nenhum endpoint existente foi substituido.

## Testes atualizados

- `pytest -q backend/tests/test_pcp_timeline_eta_unit.py`
  - Resultado: `5 passed`.
- `pytest backend/tests/test_pcp_timeline_eta_unit.py backend/tests/test_pcp_alerts_unit.py backend/tests/test_pcp_allocations_unit.py backend/tests/test_pcp_routes_unit.py backend/tests/test_pd_pipeline_auto_sync.py backend/tests/test_formula_client_links_unit.py backend/tests/test_card_governance_unit.py backend/tests/test_commercial_packages_unit.py backend/tests/test_order_generator_unit.py backend/tests/test_unified_attachments_unit.py backend/tests/test_wms_recebimento_unit.py`
  - Resultado: `86 passed`.
- `pytest backend/tests`
  - Resultado: `145 passed, 278 skipped`.
