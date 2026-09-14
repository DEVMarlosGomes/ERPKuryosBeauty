# PCP DELTA DATA CHANGES

Data: 2026-09-11

## Novos campos opcionais

### `orders.items[].id`

Identificador estavel do item do pedido.

Compatibilidade:
- pedidos antigos podem nao ter esse campo;
- rotas v2 de alocacao fazem backfill add-only quando necessario;
- rotas antigas continuam aceitando itens sem `id`.

### `orders.pcp_allocation_ids`

Lista opcional de alocacoes PCP associadas ao pedido.

### `ops.allocation_id`

ID da alocacao que originou a OP v2.

### `ops.sales_order_item_id`

ID do item de pedido consumido pela OP v2.

## Nova colecao logica: `pcp_allocations`

Campos principais:

```text
id
tenant_id
sales_order_id
sales_order_numero
sales_order_item_id
sku_id
codigo_kuryos
item_nome
planned_quantity
consumed_quantity
remaining_quantity
production_order_ids[]
line_id
planned_start
planned_end
priority
status
notes
override_excess
override_reason
created_at
updated_at
created_by
created_by_name
```

Status usados neste slice:
- `planejado`
- `parcial`
- `coberto`
- `cancelado`/`cancelled` apenas como leitura defensiva.

## Nova colecao logica: `production_order_events`

Evento inicial registrado:
- `create_op_from_allocation`.
- `confirm_wms_picking`.

## Nova colecao logica: `wms_separacoes`

Campos principais:

```text
id
tenant_id
op_id
numero_op
pedido_id
allocation_id
sales_order_item_id
status
linhas[]
faltas[]
alertas[]
estoque_baixado
destructive_stock_movement
idempotency_key
observacoes
created_at
updated_at
created_by
created_by_name
```

Status usados neste slice:
- `confirmada`
- `confirmada_com_falta`

Compatibilidade:
- `estoque_baixado` nasce `false`;
- nao ha decremento automatico em `estoque_saldos_lote`;
- OP recebe apenas campos opcionais `wms_separacao_id` e `wms_separacao_status`.

## Indices candidatos

Ainda nao aplicados automaticamente.

```text
pcp_allocations(tenant_id, sales_order_id, sales_order_item_id)
pcp_allocations(tenant_id, status)
pcp_allocations(tenant_id, sku_id, status)
ops(tenant_id, pedido_id, sales_order_item_id, status)
production_order_events(tenant_id, op_id, created_at)
wms_separacoes(tenant_id, op_id, status)
wms_separacoes(tenant_id, idempotency_key)
pcp_alerts(tenant_id, status, severidade)
pcp_alerts(tenant_id, tipo, last_sent_at)
wms_inventarios_ciclicos(tenant_id, status, created_at)
wms_inventarios_ciclicos(tenant_id, setor, status)
wms_destinacoes(tenant_id, status, created_at)
wms_destinacoes(tenant_id, saldo_lote_id, status)
recebimentos(tenant_id, recebimento_key)
recebimentos(tenant_id, idempotency_key)
materiais(tenant_id, ncm)
```

## Migracao

Nenhuma migration destrutiva foi criada ou executada.

## Nova colecao logica: `pcp_alerts`

Campos principais:

```text
id
tenant_id
alert_key
tipo
severidade
status
slot_id
numero_prog
op_id
op_numero
pedido_id
pedido_numero
linha_id
linha_nome
produto_nome
sku
planned_at
deadline_at
detected_at
last_sent_at
tolerance_minutes
cooldown_minutes
atraso_minutos
atraso_pos_tolerancia_minutos
repiques
notificacao_externa_enviada
message
created_at
updated_at
resolved_by
resolved_by_name
resolved_at
```

Tipos usados neste slice:
- `op_inicio_atrasado`
- `op_em_andamento_atrasada`

Status usados neste slice:
- `aberto`
- `resolvido`

Compatibilidade:
- alertas sao add-only e nao alteram `pcp_programacao` nem `ops`;
- `notificacao_externa_enviada` nasce `false`;
- repique atualiza o alerta aberto em vez de criar duplicata.

## Nova colecao logica: `wms_inventarios_ciclicos`

Campos principais:

```text
id
tenant_id
titulo
status
setor
item_ids[]
endereco_ids[]
somente_com_saldo
blind_count
linhas[]
total_linhas
linhas_contadas
linhas_com_divergencia
ajustes_aplicados
ajuste_movimento_ids[]
observacoes
created_by
created_by_name
created_at
updated_at
fechado_por
fechado_por_name
fechado_em
fechamento_observacoes
```

Campos principais de `linhas[]`:

```text
saldo_lote_id
item_id
item_nome
codigo_item
lote
validade
endereco_id
endereco_codigo
setor
unidade
quantidade_sistema
quantidade_contada
divergencia
divergencia_abs
status
observacoes
contado_por
contado_por_name
contado_em
```

Status usados neste slice:
- `aberto`
- `em_contagem`
- `fechado`
- `cancelado` apenas como reserva de contrato.

Compatibilidade:
- `quantidade_sistema` e snapshot interno para contagem cega;
- abertura e contagem nao alteram `estoque_saldos_lote`;
- fechamento com ajuste reutiliza `estoque_movimentos_lote` e `estoque_saldos_lote`;
- ajuste e bloqueado se o saldo atual mudou apos o snapshot.

## Nova colecao logica: `wms_destinacoes`

Campos principais:

```text
id
tenant_id
saldo_lote_id
item_id
item_nome
codigo_item
lote
validade
endereco_id
endereco_codigo
setor
unidade
quantidade
quantidade_sistema_snapshot
tipo
motivo
destino
origem_tipo
origem_id
status
baixa_aplicada
movimento_id
coleta
documento_destino
comprovante
created_by
created_by_name
created_at
updated_at
confirmado_por
confirmado_por_name
confirmado_em
cancelado_por
cancelado_por_name
cancelado_em
cancelamento_motivo
```

Tipos usados neste slice:
- `descarte`
- `devolucao_fornecedor`
- `logistica_reversa`
- `reprocesso`

Status usados neste slice:
- `solicitado`
- `coleta_programada`
- `confirmado`
- `cancelado`

Compatibilidade:
- criacao e coleta nao alteram `estoque_saldos_lote`;
- confirmacao aplica baixa via ajuste WMS existente e grava `movimento_id`;
- confirmacao repetida nao cria novo movimento;
- destinos abertos entram no bloqueio logico de excesso por saldo.

## Novos campos opcionais de recebimento

### `recebimentos.recebimento_key`

Chave logica usada para replay idempotente quando `receiving_internal_lot_v2` esta ligado.

### `recebimentos.idempotency_key`

Chave enviada pelo cliente/integracao. Quando informada, tem prioridade sobre a chave calculada.

### `recebimentos.receiving_internal_lot_v2`

Marcador booleano de que o recebimento foi criado pelo fluxo estendido.

### `recebimentos.items[].lote_interno`

Lote interno operacional no padrao `AK-AAAA-NNNNNN`.

### Campos propagados

O mesmo lote interno pode aparecer, de forma opcional, em:
- `cq_registros_analise.lote_interno`;
- `estoque_items.lote_interno`;
- `estoque_items.lote_fornecedor`;
- `estoque_movimentos.lote_interno`;
- `estoque_movimentos.lote_fornecedor`;
- `estoque_saldos_lote.lote_interno`;
- `estoque_saldos_lote.lote_fornecedor`;
- `wms_paletes.lote_interno`;
- `wms_paletes.lote_fornecedor`;
- `compras_pos.nfs_vinculadas[].recebimento_key`;
- `compras_pos.nfs_vinculadas[].itens[].lote_interno`.

Compatibilidade:
- campos sao opcionais;
- pedidos/recebimentos antigos sem esses campos continuam validos;
- o replay idempotente retorna documento existente sem novos efeitos colaterais.

## Novos campos opcionais de materiais fiscais

Campos opcionais em `materiais`:

```text
ncm
cest
ipi_default
icms_st_default
origem_fiscal
observacoes_fiscais
material_tax_defaults_v2
fiscal_updated_by
fiscal_updated_by_name
fiscal_updated_at
```

Compatibilidade:
- materiais antigos sem esses campos continuam validos;
- compras, PO, recebimento e faturamento nao passam a exigir os defaults fiscais;
- `ncm` e `cest` sao armazenados apenas com digitos;
- percentuais sao armazenados como numeros entre 0 e 100.

## Nova colecao `commercial_packages`

Snapshot comercial historico por amostra/variacao aprovada pelo cliente.

Campos principais:

```text
id
tenant_id
sample_id
variacao_id
sku_id
projeto_id
cliente_id
status
source
feature
package_version
idempotency_key
pedido_cliente_ref
frete
condicoes
anexos
snapshot
observacoes
created_by
created_by_name
created_at
updated_at
```

Indices candidatos:
- `commercial_packages(tenant_id, sample_id, variacao_id, package_version)`;
- `commercial_packages(tenant_id, sample_id, variacao_id, idempotency_key)` unico e parcial para chaves string.

Compatibilidade:
- a colecao e add-only e nao substitui `orders`, `kickoffs`, `contratos`, `skus` ou anexos atuais;
- pacotes antigos/novos sao snapshots independentes por versao;
- documentos sem `idempotency_key` continuam validos e nao entram no indice parcial de replay.

## Nova colecao `attachments`

Metadados unificados de anexos por entidade dona, sem substituir `files` nem campos locais existentes.

Campos principais:

```text
id
tenant_id
owner_type
owner_id
entity_type
entity_id
relation
file_id
legacy_attachment_id
original_filename
content_type
size
storage_backend
storage_path
download_url
uploaded_by
uploaded_by_name
uploaded_at
created_at
updated_at
is_deleted
source
feature
```

Indices candidatos:
- `attachments(tenant_id, entity_type, entity_id, uploaded_at)`;
- `attachments(tenant_id, owner_type, owner_id, uploaded_at)`;
- `attachments(tenant_id, file_id)` sparse.

Compatibilidade:
- `files` continua armazenando os objetos genericos;
- `orders.attachments` continua existindo para compatibilidade do pedido;
- anexos locais antigos de pedido podem ser expostos como metadados unificados sinteticos;
- novos documentos podem apontar para `storage_backend=object` ou `storage_backend=local`.

## Campos opcionais de card governance

Campos adicionados de forma opcional em `crm_projects`, `crm_samples`, `crm_samples.variacoes[]`,
`pd_requests` e `pd_cards`:

```text
is_deleted
deleted_at
deleted_by
deleted_by_name
delete_reason
restored_at
restored_by
restored_by_name
restore_reason
```

Indices candidatos:
- `crm_projects(tenant_id, is_deleted, updated_at)`;
- `crm_samples(tenant_id, is_deleted, updated_at)`;
- `pd_requests(tenant_id, is_deleted, updated_at)`.

Compatibilidade:
- campos sao opcionais;
- documentos sem `is_deleted` continuam validos;
- listagens antigas nao foram alteradas para filtrar estes campos nesta fase;
- restore preserva o status funcional original do documento.

## Nova colecao `formula_client_links`

Vinculos comerciais explicitos entre formulas existentes do banco de formulas e clientes, sem substituir formula, BOM,
Produto-Pai, SKU ou projeto comercial.

Campos principais:

```text
id
tenant_id
formula_id
development_id
pd_request_id
cliente_id
cliente_nome
uso_comercial
projeto_id
sku_id
produto_pai_id
status
observacoes
formula_snapshot
source_request_snapshot
idempotency_key
feature
created_by
created_by_name
created_at
updated_at
inactivated_at
inactivated_by
inactivated_by_name
inactivation_reason
```

Indices candidatos:
- `formula_client_links(tenant_id, formula_id, status)`;
- `formula_client_links(tenant_id, cliente_id, status)`;
- `formula_client_links(tenant_id, formula_id, idempotency_key)` unico e parcial para chaves string;
- `formula_client_links(tenant_id, formula_id, cliente_id, uso_comercial)` unico e parcial para `ativo`/`em_validacao`.

Compatibilidade:
- a colecao e add-only e nao altera documentos existentes de formulas, produtos, SKUs, projetos ou clientes;
- vinculos inativos permanecem como historico;
- formulas ainda nao registradas geram vinculos `em_validacao`, sem promover uso comercial ativo automaticamente;
- documentos sem `idempotency_key` continuam validos e nao entram no indice parcial de replay;
- `formula_snapshot` e `source_request_snapshot` sao snapshots auxiliares e nao passam a ser fonte transacional.

## Campos opcionais D48 policy/snapshot

Campos adicionados de forma opcional em `tenant_settings.pd`:

```text
require_d48
d48_policy_version
d48_policy.required
d48_policy.version
d48_policy.updated_at
d48_policy.updated_by
d48_policy.updated_by_name
d48_policy.reason
```

Campos adicionados de forma opcional em `pd_requests`, `pd_samples` e `pd_cards` quando o gate D48 e avaliado:

```text
d48_required_override
d48_override_reason
d48_override_policy_version
d48_override_updated_at
d48_override_updated_by
d48_override_updated_by_name
d48_required_snapshot
d48_policy_version
d48_policy_source
d48_gate_checked_at
d48_gate_satisfied_at
d48_gate_skipped_at
```

Compatibilidade:
- documentos antigos sem estes campos continuam exigindo D48 por padrao;
- override por card/requisicao e opcional e nao remove o gate global;
- snapshot e auditoria historica da decisao aplicada, nao substitui leituras em `pd_stability_studies`;
- quando `require_d48=false`, a entrega e liberada com `d48_gate_skipped_at` para rastreabilidade.

## Campos opcionais PCP timeline/ETA

Feature flag em `tenant_settings.features`:

```text
pcp_timeline_eta_v2
```

Eventos add-only em `production_order_events`:

```text
id
tenant_id
op_id
op_numero
sales_order_id
allocation_id
event_type
action
started_at
ended_at
duration_minutes
payload.quantity
payload.reason
payload.note
payload.setup_type
payload.metadata
idempotency_key
created_at
created_by
created_by_name
```

Nova colecao `pcp_day_closings`:

```text
id
tenant_id
data
turno
status
kpis.ops_movimentadas
kpis.ops_concluidas
kpis.slots_planejados
kpis.slots_concluidos
kpis.qtd_produzida
kpis.qtd_perdas
kpis.perda_pct
kpis.paradas_minutos
kpis.setup_minutos
kpis.divergencias_reconciliacao
reconciliacao[]
op_ids[]
slot_ids[]
event_ids[]
observacoes
metadata
idempotency_key
snapshot_version
created_at
updated_at
created_by
created_by_name
```

Indices candidatos:
- `production_order_events(tenant_id, op_id, created_at)`;
- `production_order_events(tenant_id, op_id, idempotency_key)` parcial para chaves string;
- `pcp_day_closings(tenant_id, data, turno)`;
- `pcp_day_closings(tenant_id, idempotency_key)` parcial para chaves string.

Compatibilidade:
- eventos novos nao substituem `ops.apontamentos`, `ops.perdas` ou `ops.pausas`;
- timeline e ETA sao leituras agregadas e nao alteram status de OP, slot, lote ou pedido;
- fechamentos diarios sao snapshots auditaveis e podem ser recalculados sem apagar historico operacional de origem;
- documentos antigos sem eventos continuam validos e retornam ETA por ritmo geral quando houver apontamento.

## Contrato opcional qualidade de fornecedor na cotacao

Feature flag em `tenant_settings.features`:

```text
pcp_supplier_quality_quote_v2
```

Este passe nao adiciona colecao nem migration. O enriquecimento reutiliza campos ja existentes em
`compras_fornecedores.homologacao`:

```text
homologacao.status
homologacao.proxima_reavaliacao
homologacao.historico_rncs_count
homologacao.historico_rncs_criticas_12m
homologacao.historico[]
```

Campo derivado opcional em respostas de cotacao/comparador:

```text
supplier_quality.score
supplier_quality.selo
supplier_quality.risco
supplier_quality.status_homologacao
supplier_quality.status_cadastro
supplier_quality.proxima_reavaliacao
supplier_quality.dias_reavaliacao
supplier_quality.rnc_total
supplier_quality.rnc_criticas_12m
supplier_quality.rnc_abertas
supplier_quality.alertas[]
supplier_quality.fontes[]
```

Compatibilidade:
- documentos antigos sem historico de RNC continuam validos;
- ausencia de flag deve manter as respostas atuais sem `supplier_quality`;
- `supplier_quality` e dado calculado/snapshot de apresentacao, nao fonte transacional;
- reavaliacao vencida ou fornecedor suspenso/reprovado deve elevar risco sem alterar automaticamente PO, demanda ou cotacao.

## Contrato opcional quarentena fisica WMS

Feature flag em `tenant_settings.features`:

```text
wms_physical_quarantine_v2
```

Configuracao por tenant em `tenant_settings.wms.quarantine`:

```text
endereco_id
endereco_codigo
auto_route_recebimento
policy_version
motivo
observacoes
updated_at
updated_by
updated_by_name
```

Campos opcionais em `estoque_saldos_lote`:

```text
wms_quarantine_physical
wms_quarantine_status
wms_quarantine_policy_version
wms_quarantine_last_movement_id
wms_quarantine_address_id
wms_quarantine_address_codigo
wms_quarantine_entered_at
wms_quarantine_exited_at
wms_quarantine_updated_at
```

Movimentos auditaveis em `wms_quarantine_movements`:

```text
wms_quarantine_movements.id
wms_quarantine_movements.tenant_id
wms_quarantine_movements.action
wms_quarantine_movements.saldo_lote_origem_id
wms_quarantine_movements.saldo_lote_destino_id
wms_quarantine_movements.item_id
wms_quarantine_movements.item_nome
wms_quarantine_movements.codigo_item
wms_quarantine_movements.lote
wms_quarantine_movements.direcao
wms_quarantine_movements.quantidade
wms_quarantine_movements.unidade
wms_quarantine_movements.cq_logico
wms_quarantine_movements.origem
wms_quarantine_movements.destino
wms_quarantine_movements.policy_snapshot
wms_quarantine_movements.transfer_reference
wms_quarantine_movements.movimento_lote_ids[]
wms_quarantine_movements.idempotency_key
wms_quarantine_movements.motivo
wms_quarantine_movements.documento
wms_quarantine_movements.observacoes
wms_quarantine_movements.created_at
wms_quarantine_movements.usuario
wms_quarantine_movements.usuario_id
```

Compatibilidade:
- `posicao_cq` continua sendo o bloqueio logico de qualidade;
- localizacao fisica de quarentena nao deve transformar automaticamente CQ em aprovado/reprovado;
- consumo, expedicao e baixa produtiva continuam bloqueados por CQ enquanto `posicao_cq` estiver em quarentena/reprovado;
- documentos antigos sem `wms_quarantine_physical` devem ser tratados como fora da area fisica configurada, exceto saldos
  no endereco configurado pela politica atual;
- a rota de quarentena fisica registra transferencia WMS controlada, mas nao altera quantidade agregada do item.
