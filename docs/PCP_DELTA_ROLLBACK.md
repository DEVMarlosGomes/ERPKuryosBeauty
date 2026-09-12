# PCP DELTA ROLLBACK

Data: 2026-09-11

## Slice 1 - `pcp_quantity_planning_v2`

Rollback operacional:

1. Desligar `tenant_settings.features.pcp_quantity_planning_v2`.
2. Parar de chamar as rotas novas de alocacao.
3. Manter `pcp_allocations` e `production_order_events` como historico/auditoria.
4. Continuar usando `POST /api/orders/{order_id}/create-op` para o fluxo antigo.

## Dados

Nao apagar automaticamente:
- `pcp_allocations`;
- `production_order_events`;
- `orders.items[].id`;
- `orders.pcp_allocation_ids`;
- `ops.allocation_id`;
- `ops.sales_order_item_id`.

Esses campos sao opcionais e nao quebram os fluxos antigos.

## Reversao de codigo

O slice e isolado principalmente em:
- `backend/orders_routes.py`;
- `backend/tests/test_pcp_allocations_unit.py`.

Nao houve alteracao funcional de frontend.

## Slice 2 - UI Quantidades

Rollback operacional:

1. Remover/ocultar acesso de menu para `/pcp/planejamento/quantidades`.
2. Manter `/pcp/planejamento` no fluxo anterior.
3. Desligar `tenant_settings.features.pcp_quantity_planning_v2`.

## Slice 3 - `pcp_material_picking_v2`

Rollback operacional:

1. Desligar `tenant_settings.features.pcp_material_picking_v2`.
2. Parar de chamar as rotas novas de separacao.
3. Manter `wms_separacoes` e `production_order_events` como historico/auditoria.
4. Continuar usando WMS/Estoque manual atual.

Dados opcionais que podem permanecer:
- `wms_separacoes`;
- `ops.wms_separacao_id`;
- `ops.wms_separacao_status`;
- eventos `confirm_wms_picking`.

Nao ha baixa automatica de estoque neste slice, entao rollback nao exige estorno de saldo.

## Slice 4 - UI FEFO no Detalhe da OP

Rollback operacional:

1. Desligar `tenant_settings.features.pcp_material_picking_v2`.
2. O painel passa a exibir a feature como inativa.
3. O fluxo antigo de OP/apontamento segue intacto.

Rollback de codigo:
- remover o painel `Separacao FEFO / WMS` de `frontend/src/pages/OPDetail.js`.

## Slice 5 - `pcp_alerts_enabled`

Rollback operacional:

1. Desligar `tenant_settings.features.pcp_alerts_enabled`.
2. Parar de chamar `POST /api/pcp/alerts/check`.
3. Manter `pcp_alerts` como historico/auditoria.

Dados opcionais que podem permanecer:
- `pcp_alerts`;
- campos de resolucao nos alertas;
- contadores de `repiques`.

Nao ha envio externo automatico neste slice e nenhum status de slot/OP e alterado pelos alertas.

Rollback de codigo:
- remover a secao `ALERTAS PCP` de `backend/pcp_routes.py`;
- remover `backend/tests/test_pcp_alerts_unit.py`.

## Slice 6 - `wms_cycle_count_v2`

Rollback operacional:

1. Desligar `tenant_settings.features.wms_cycle_count_v2`.
2. Parar de chamar as rotas de `/api/estoque/wms/inventarios-ciclicos`.
3. Manter `wms_inventarios_ciclicos` como historico/auditoria.
4. Continuar usando o ajuste WMS atual em `/api/estoque/wms/saldos/ajustar`.

Dados opcionais que podem permanecer:
- `wms_inventarios_ciclicos`;
- snapshots de `linhas[]`;
- `ajuste_movimento_ids[]` referenciando kardex.

Abertura e contagem nao alteram saldo. Se um inventario ja foi fechado com ajuste, o estorno deve usar o fluxo
operacional existente de ajuste WMS, preservando o kardex.

Rollback de codigo:
- remover as rotas `inventarios-ciclicos` de `backend/estoque_routes.py`;
- remover os testes adicionados em `backend/tests/test_wms_recebimento_unit.py`.

## Slice 7 - `pcp_disposal_v2`

Rollback operacional:

1. Desligar `tenant_settings.features.pcp_disposal_v2`.
2. Parar de chamar as rotas de `/api/estoque/wms/destinacoes`.
3. Manter `wms_destinacoes` como historico/auditoria.
4. Continuar usando o ajuste WMS atual em `/api/estoque/wms/saldos/ajustar` para qualquer correcao operacional.

Dados opcionais que podem permanecer:
- `wms_destinacoes`;
- `coleta`;
- `movimento_id` apontando para o kardex.

Criacao e coleta nao alteram saldo. Se uma destinacao foi confirmada, a baixa ja esta registrada no kardex; qualquer
estorno deve usar o fluxo operacional existente de ajuste WMS.

Rollback de codigo:
- remover as rotas `destinacoes` de `backend/estoque_routes.py`;
- remover os testes de destinacao adicionados em `backend/tests/test_wms_recebimento_unit.py`.

## Slice 8 - `receiving_internal_lot_v2`

Rollback operacional:

1. Desligar `tenant_settings.features.receiving_internal_lot_v2`.
2. Continuar usando `POST /api/recebimento/entradas` sem `idempotency_key` e sem `lote_interno`.
3. Manter os campos opcionais ja gravados como historico/rastreabilidade.

Dados opcionais que podem permanecer:
- `recebimentos.recebimento_key`;
- `recebimentos.idempotency_key`;
- `recebimentos.items[].lote_interno`;
- campos `lote_interno`/`lote_fornecedor` propagados para CQ, estoque, WMS e PO.

Nao ha migration destrutiva. Recebimentos ja criados pelo fluxo estendido continuam legiveis pelo fluxo antigo porque
os novos campos sao opcionais.

Rollback de codigo:
- remover helpers/model fields de lote interno em `backend/recebimento_routes.py`;
- remover o teste de idempotencia/lote interno de `backend/tests/test_wms_recebimento_unit.py`.

## Slice 9 - `material_tax_defaults_v2`

Rollback operacional:

1. Desligar `tenant_settings.features.material_tax_defaults_v2`.
2. Parar de enviar `fiscal_defaults` nas rotas de materiais.
3. Parar de chamar `/api/cadastros/materiais/{codigo_interno}/fiscal-defaults`.
4. Manter os campos fiscais ja gravados como historico/cadastro complementar.

Dados opcionais que podem permanecer:
- `materiais.ncm`;
- `materiais.cest`;
- `materiais.ipi_default`;
- `materiais.icms_st_default`;
- `materiais.origem_fiscal`;
- `materiais.observacoes_fiscais`;
- campos de auditoria fiscal.

Nao ha calculo fiscal automatico neste slice, entao desligar a flag impede novas gravacoes fiscais sem afetar compras,
PO, recebimento ou faturamento.

Rollback de codigo:
- remover `MaterialFiscalDefaults` e helpers fiscais de `backend/materiais_routes.py`;
- remover a rota `fiscal-defaults`;
- remover `backend/tests/test_materiais_fiscal_defaults_unit.py`.

## Slice 10 - `v21_commercial_package`

Rollback operacional:

1. Desligar `tenant_settings.features.v21_commercial_package`.
2. Parar de chamar as rotas `/api/crm/samples/{sample_id}/variacoes/{variacao_id}/commercial-packages`.
3. Manter `commercial_packages` como historico/auditoria.
4. Continuar usando os fluxos atuais de aprovacao de amostra, SKU, pedido, Kickoff e CGI/contratos.

Dados opcionais que podem permanecer:
- documentos em `commercial_packages`;
- `snapshot`;
- `frete`;
- `condicoes`;
- `anexos`;
- `idempotency_key`.

Nao ha migration destrutiva e nenhum fluxo transacional passa a depender do pacote. Desligar a flag bloqueia novas
leituras/escritas pelas rotas adicionadas.

Rollback de codigo:
- remover modelos/helpers/rotas de pacote comercial de `backend/crm_routes.py`;
- remover indices `commercial_packages` adicionados em `backend/server.py`;
- remover `backend/tests/test_commercial_packages_unit.py`.

## Slice 11 - `unified_attachments_v2`

Rollback operacional:

1. Desligar `tenant_settings.features.unified_attachments_v2`.
2. Continuar usando `/api/upload` sem `owner_type/owner_id` para arquivos genericos.
3. Continuar usando `/api/orders/{order_id}/attachments` e o download legado de pedidos.
4. Manter `attachments` como historico/metadado auxiliar.

Dados opcionais que podem permanecer:
- documentos em `attachments`;
- `orders.attachments[].storage_backend`;
- `orders.attachments[].file_id`;
- `orders.attachments[].unified_attachment_v2`;
- registros em `files` criados por upload de pedido via object storage.

Nao ha migration destrutiva. Pedidos antigos continuam baixando arquivos pela pasta local; novos anexos de pedido com
object storage continuam referenciados tambem em `orders.attachments`.

Rollback de codigo:
- remover helpers/rotas de attachments unificados em `backend/server.py`;
- remover extensoes de storage/metadata de `backend/orders_routes.py`;
- remover indices `attachments` de `backend/server.py`;
- remover `backend/tests/test_unified_attachments_unit.py`;
- remover os testes de anexos unificados adicionados em `backend/tests/test_order_generator_unit.py`.

## Slice 12 - `v21_card_governance`

Rollback operacional:

1. Desligar `tenant_settings.features.v21_card_governance`.
2. Parar de chamar as rotas `/archive` e `/restore` adicionadas em CRM/P&D.
3. Manter os campos de governanca ja gravados como historico/auditoria.
4. Continuar usando os fluxos e DELETEs atuais.

Dados opcionais que podem permanecer:
- `is_deleted`;
- `deleted_at`;
- `deleted_by`;
- `deleted_by_name`;
- `delete_reason`;
- `restored_at`;
- `restored_by`;
- `restored_by_name`;
- `restore_reason`.

Nao ha migration destrutiva. Como as listagens atuais nao foram alteradas, desligar a flag apenas bloqueia novas
operacoes governadas.

Rollback de codigo:
- remover modelos/helpers/rotas de governanca de `backend/crm_routes.py`;
- remover modelos/helpers/rotas de governanca de `backend/pd_routes.py`;
- remover indices `is_deleted` adicionados em `backend/server.py`;
- remover `backend/tests/test_card_governance_unit.py`.
