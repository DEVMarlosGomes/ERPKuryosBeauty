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
