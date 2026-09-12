# PCP DELTA API CHANGES

Data: 2026-09-11

## Slice 1 - Planejamento de Quantidades

Todas as rotas abaixo sao novas, add-only, e exigem a feature flag `pcp_quantity_planning_v2` ligada em
`tenant_settings.features`.

## `GET /api/orders/{order_id}/pcp-allocations`

Lista alocacoes PCP de um pedido.

Preserva:
- nao altera o pedido, exceto backfill add-only de `items[].id` caso existam itens legados sem ID.

## `POST /api/orders/{order_id}/items/{item_id}/pcp-allocations`

Cria uma alocacao de quantidade para um item de pedido.

Payload:

```json
{
  "planned_quantity": 100,
  "line_id": "linha-1",
  "planned_start": "2026-09-11T08:00:00-03:00",
  "planned_end": "2026-09-11T09:18:00-03:00",
  "priority": 0,
  "notes": "",
  "override_excess": false,
  "override_reason": null
}
```

Regras:
- pedido deve estar `confirmado` ou `em_producao`;
- `planned_quantity` deve ser maior que zero;
- soma das alocacoes ativas do item nao pode exceder `items[].qtd`;
- override de excesso exige `admin` e motivo.

## `POST /api/orders/{order_id}/pcp-allocations/{allocation_id}/create-op`

Cria uma OP para consumir parte ou todo o saldo de uma alocacao.

Payload:

```json
{
  "quantity": 40,
  "observacoes": "Primeiro lote",
  "override_excess": false,
  "override_reason": null
}
```

Regras:
- pedido deve estar `confirmado` ou `em_producao`;
- alocacao nao pode estar cancelada;
- `quantity` deve ser maior que zero;
- quantidade nao pode exceder saldo da alocacao sem override;
- OP criada recebe `allocation_id`, `sales_order_item_id` e item unico ligado ao item do pedido.

## Compatibilidade

Nao houve alteracao em rotas antigas. O endpoint `POST /api/orders/{order_id}/create-op` permanece disponivel.

## Slice 2 - UI

Nova rota frontend:

```text
/pcp/planejamento/quantidades
```

Ela consome as APIs do Slice 1 e nao altera `/pcp/planejamento`.

## Slice 3 - Separacao FEFO por OP

Todas as rotas abaixo sao novas e exigem `tenant_settings.features.pcp_material_picking_v2`.

## `GET /api/ops/{op_id}/material-picking/suggestion`

Alias preservado:

```text
GET /api/ops/{op_id}/wms-separacao/sugestao
```

Retorna sugestao de separacao por material, ordenada por FEFO.

Regras:
- usa OP existente;
- resolve BOM vigente por SKU/Produto-Pai quando disponivel;
- usa `estoque_saldos_lote` e `wms_enderecos`;
- ignora lote sem saldo, quarentena, reprovado, bloqueado, segregado ou endereco WMS bloqueado;
- nao baixa estoque.

## `POST /api/ops/{op_id}/material-picking/confirm`

Alias preservado:

```text
POST /api/ops/{op_id}/wms-separacao/confirmar
```

Payload:

```json
{
  "idempotency_key": "op-1-sep-20260911",
  "linhas": [],
  "observacoes": ""
}
```

Quando `linhas` vier vazio, confirma as linhas sugeridas elegiveis. A confirmacao cria `wms_separacoes`,
registra evento de OP e atualiza a OP com o status da separacao, sem baixa fisica de estoque.

## Slice 4 - Consumo UI

`OPDetail` passa a consumir:

```text
GET /api/ops/{op_id}/material-picking/suggestion
POST /api/ops/{op_id}/material-picking/confirm
```

Nao ha nova rota backend neste slice alem dos aliases ja documentados.

## Slice 5 - Alertas PCP

Todas as rotas abaixo sao novas e exigem `tenant_settings.features.pcp_alerts_enabled`.

## `GET /api/pcp/alerts`

Lista alertas PCP.

Parametros opcionais:

```text
status
tipo
limit
```

Tipos criados neste slice:
- `op_inicio_atrasado`
- `op_em_andamento_atrasada`

Status criados neste slice:
- `aberto`
- `resolvido`

## `POST /api/pcp/alerts/check`

Executa avaliacao manual de programacao PCP.

Payload:

```json
{
  "now": "2026-09-11T10:00:00-03:00",
  "tolerance_minutes": 5,
  "cooldown_minutes": 10,
  "dry_run": false
}
```

Regras:
- slots `planejado` geram alerta quando `data_inicio` + `hora_inicio` estoura a tolerancia;
- slots `em_execucao` geram alerta quando `data_fim` + `hora_fim` estoura a tolerancia;
- alertas abertos/pendentes usam `alert_key` para evitar duplicidade;
- apos o cooldown, o mesmo alerta recebe repique em vez de duplicata;
- `dry_run=true` retorna candidatos sem gravar `pcp_alerts`.

## `PUT /api/pcp/alerts/{alert_id}/resolve`

Marca alerta como `resolvido` e registra usuario/data de resolucao.

## Slice 6 - Inventario ciclico WMS

Todas as rotas abaixo sao novas e exigem `tenant_settings.features.wms_cycle_count_v2`.

## `GET /api/estoque/wms/inventarios-ciclicos`

Lista inventarios ciclicos.

Parametros opcionais:

```text
status
limit
```

## `POST /api/estoque/wms/inventarios-ciclicos`

Abre um inventario ciclico criando snapshot dos saldos atuais.

Payload:

```json
{
  "titulo": "Inventario ciclico WMS",
  "setor": "LOGISTICA",
  "item_ids": [],
  "endereco_ids": [],
  "somente_com_saldo": true,
  "observacoes": ""
}
```

Regras:
- usa `estoque_saldos_lote` como fonte;
- retorno padrao omite `quantidade_sistema` enquanto o inventario esta aberto/em contagem;
- nao ajusta estoque na abertura.

## `GET /api/estoque/wms/inventarios-ciclicos/{inventario_id}`

Retorna inventario ciclico. `reveal_system=true` mostra quantidades do snapshot e divergencias calculadas.

## `POST /api/estoque/wms/inventarios-ciclicos/{inventario_id}/contagens`

Registra contagem por linha.

Payload:

```json
{
  "linhas": [
    {
      "saldo_lote_id": "saldo-1",
      "quantidade_contada": 96,
      "observacoes": "recontagem cega"
    }
  ],
  "observacoes": ""
}
```

Regras:
- aceita inventario `aberto` ou `em_contagem`;
- calcula divergencia internamente;
- nao ajusta estoque durante a contagem.

## `POST /api/estoque/wms/inventarios-ciclicos/{inventario_id}/fechar`

Fecha inventario com ou sem ajuste.

Payload:

```json
{
  "aplicar_ajustes": true,
  "motivo": "contagem mensal",
  "observacoes": "aprovado pelo lider"
}
```

Regras:
- exige todas as linhas contadas;
- se `aplicar_ajustes=true`, `motivo` e obrigatorio;
- antes de ajustar, confirma que o saldo atual ainda bate com o snapshot;
- ajustes usam o fluxo existente de `wms/saldos/ajustar` e registram kardex em `estoque_movimentos_lote`.

## Slice 7 - Descarte e logistica reversa WMS

Todas as rotas abaixo sao novas e exigem `tenant_settings.features.pcp_disposal_v2`.

## `GET /api/estoque/wms/destinacoes`

Lista destinacoes WMS.

Parametros opcionais:

```text
status
tipo
limit
```

## `POST /api/estoque/wms/destinacoes`

Cria uma destinacao sobre um saldo de lote/endereco.

Payload:

```json
{
  "saldo_lote_id": "saldo-1",
  "quantidade": 40,
  "tipo": "logistica_reversa",
  "motivo": "nao conformidade do fornecedor",
  "destino": "Fornecedor A",
  "origem_tipo": "rnc",
  "origem_id": "rnc-1",
  "observacoes": ""
}
```

Tipos aceitos:
- `descarte`
- `devolucao_fornecedor`
- `logistica_reversa`
- `reprocesso`

Regras:
- nao altera saldo na criacao;
- bloqueia excesso considerando saldo atual e destinacoes `solicitado`/`coleta_programada` do mesmo saldo.

## `PUT /api/estoque/wms/destinacoes/{destinacao_id}/coleta`

Programa coleta/destino fisico.

Payload:

```json
{
  "data_coleta": "2026-09-11",
  "responsavel": "Transportadora",
  "documento": "COLETA-1",
  "observacoes": ""
}
```

## `POST /api/estoque/wms/destinacoes/{destinacao_id}/confirmar`

Confirma a destinacao e aplica baixa de estoque.

Payload:

```json
{
  "documento_destino": "COLETA-1",
  "comprovante": "canhoto-1",
  "observacoes": ""
}
```

Regras:
- destinacao cancelada nao pode ser confirmada;
- confirmacao repetida retorna a destinacao ja confirmada sem nova baixa;
- baixa usa o ajuste WMS existente em modo `saida` e registra `AJUSTE_SAIDA`.

## `POST /api/estoque/wms/destinacoes/{destinacao_id}/cancelar`

Cancela destinacao antes da confirmacao.

Payload:

```json
{
  "motivo": "destinacao reavaliada"
}
```

## Slice 8 - Lote interno e idempotencia de recebimento

Extensao add-only do endpoint existente, ativada por `tenant_settings.features.receiving_internal_lot_v2`.

## `POST /api/recebimento/entradas`

Campos opcionais adicionados ao payload:

```json
{
  "idempotency_key": "po-1-nf-100-item-1",
  "items": [
    {
      "lote_interno": "AK-2026-000001"
    }
  ]
}
```

Regras quando a flag esta ligada:
- se `idempotency_key` for informado, ele vira a `recebimento_key`;
- se `idempotency_key` nao for informado, a `recebimento_key` e calculada por PO/NF/fornecedor/itens;
- se ja existir recebimento com a mesma `recebimento_key`, o endpoint retorna o registro existente com
  `idempotent_replay=true`;
- se `items[].lote_interno` nao for informado, o backend gera `AK-AAAA-NNNNNN`;
- o lote interno e propagado para recebimento, RA/CQ, saldos WMS, paletes, movimento de estoque e integracao da PO.

Compatibilidade:
- com a flag desligada, `idempotency_key` e `lote_interno` nao sao exigidos;
- a rota antiga e preservada;
- nao ha endpoint novo neste slice.

## Slice 9 - Defaults fiscais de material

Extensao add-only do cadastro de materiais comprados, ativada por
`tenant_settings.features.material_tax_defaults_v2`.

## `POST /api/cadastros/materiais`

Campo opcional adicionado:

```json
{
  "fiscal_defaults": {
    "ncm": "3304.99.10",
    "cest": "28.064.00",
    "ipi_default": 3.25,
    "icms_st_default": 12,
    "origem_fiscal": "0",
    "observacoes_fiscais": "Padrao fiscal validado"
  }
}
```

Regras:
- criar material sem `fiscal_defaults` continua permitido com a flag desligada;
- enviar `fiscal_defaults` exige a feature flag ligada;
- NCM e normalizado para 8 digitos;
- CEST e normalizado para 7 digitos;
- `ipi_default` e `icms_st_default` devem estar entre 0 e 100;
- `origem_fiscal` aceita codigos string de `0` a `8`.

## `PATCH /api/cadastros/materiais/{codigo_interno}`

Aceita o mesmo campo opcional `fiscal_defaults` quando a flag esta ligada.

## `PATCH /api/cadastros/materiais/{codigo_interno}/fiscal-defaults`

Atualiza apenas os defaults fiscais do material.

Payload:

```json
{
  "ncm": "3304.99.10",
  "cest": "28.064.00",
  "ipi_default": 3.25,
  "icms_st_default": 12,
  "origem_fiscal": "0",
  "observacoes_fiscais": "Padrao fiscal validado"
}
```

Compatibilidade:
- nao altera compras, PO, recebimento ou faturamento;
- nao calcula impostos automaticamente;
- campos sao opcionais e podem ser lidos por integracoes futuras.

## Slice 10 - Pacote comercial por aprovacao de amostra

Rotas add-only ativadas por `tenant_settings.features.v21_commercial_package`.

## `GET /api/crm/samples/{sample_id}/variacoes/{variacao_id}/commercial-packages`

Lista snapshots comerciais da variacao, ordenados pela versao mais recente.

Resposta:

```json
{
  "packages": [],
  "count": 0
}
```

## `POST /api/crm/samples/{sample_id}/variacoes/{variacao_id}/commercial-packages`

Cria um snapshot comercial somente se a variacao ja estiver aprovada pelo cliente.

Payload:

```json
{
  "idempotency_key": "sample-1-var-1-proposta-001",
  "pedido_cliente_ref": "PO-123",
  "frete": {
    "tipo": "CIF",
    "valor": 120.5,
    "endereco": "Rua 1",
    "cidade_uf": "Sao Paulo/SP",
    "prazo_coleta": "D+2"
  },
  "condicoes": {
    "percentual_nf": 80,
    "condicao_pagamento": "030/060/090",
    "prazo_entrega_dias": 25,
    "preco_unitario": 36.9,
    "preco_unitario_currency": "BRL",
    "validade_ate": "2026-10-12",
    "observacoes": "Condicoes aprovadas pelo cliente"
  },
  "anexos": [
    {
      "original_filename": "aprovacao.pdf",
      "url": "/files/aprovacao.pdf",
      "content_type": "application/pdf"
    }
  ],
  "observacoes": "Snapshot comercial inicial"
}
```

Regras:
- feature flag desligada retorna `403`;
- variacao precisa ter `status=aprovada`, `resultado=aprovada` ou `aprovacao_externa=true`;
- `idempotency_key` repetida retorna o pacote existente com `idempotent_replay=true`;
- `percentual_nf` deve ficar entre 0 e 100;
- `condicao_pagamento`, quando enviada, deve seguir `NNN/NNN/NNN`;
- campos comerciais nao atualizam pedido, Kickoff, contrato ou SKU.

## Slice 11 - Anexos unificados em object storage

Extensoes add-only ativadas por `tenant_settings.features.unified_attachments_v2`.

## `POST /api/upload`

Contrato antigo preservado. Novos parametros opcionais de query:

```text
owner_type=kickoff
owner_id=kickoff-1
relation=contrato_assinado
```

Quando `owner_type` e `owner_id` sao enviados com a flag ligada, alem de gravar em `files`, o endpoint cria um
documento em `attachments` e retorna `attachment_id` e `attachment`.

## `GET /api/attachments`

Lista anexos unificados por owner/entity.

Parametros:

```text
owner_type
owner_id
entity_type
entity_id
relation
```

`owner_type/owner_id` e `entity_type/entity_id` sao aliases. Pelo menos um par deve ser informado.

## `GET /api/attachments/{attachment_id}/download`

Baixa o arquivo associado ao documento unificado. O caminho atual usa object storage via `files` quando `file_id`
existe.

## `GET /api/orders/{order_id}/attachments/metadata`

Lista metadados unificados dos anexos de pedido. Se ainda nao houver documentos em `attachments`, retorna uma visao
compatibilizada de `orders.attachments`.

## `POST /api/orders/{order_id}/attachments`

Contrato antigo preservado. Quando a flag esta ligada:
- tenta gravar o arquivo no object storage;
- cria registro em `files` quando o object storage aceita o arquivo;
- cria/espelha metadados em `attachments`;
- se o object storage falhar, cai para armazenamento local antigo e ainda preserva `download_url` do pedido.

Compatibilidade:
- downloads antigos de pedido continuam em `/api/orders/{order_id}/attachments/{attachment_id}/download`;
- `/api/upload` sem owner nao exige a feature flag;
- os novos campos retornados sao opcionais para clientes antigos.

## Slice 12 - V21 card governance

Rotas add-only ativadas por `tenant_settings.features.v21_card_governance`.

## CRM

```text
POST /api/crm/projects/{project_id}/archive
POST /api/crm/projects/{project_id}/restore
POST /api/crm/samples/{sample_id}/archive
POST /api/crm/samples/{sample_id}/restore
POST /api/crm/samples/{sample_id}/variacoes/{variacao_id}/archive
POST /api/crm/samples/{sample_id}/variacoes/{variacao_id}/restore
```

Payload:

```json
{
  "reason": "Cliente cancelou esta alternativa"
}
```

Regras:
- motivo minimo de 5 caracteres;
- projeto com SKU/amostra aprovada nao pode ser arquivado;
- amostra/variacao aprovada, com aprovacao externa ou SKU nao pode ser arquivada;
- ultima variacao ativa nao pode ser arquivada;
- restore nao altera status original.

## P&D

```text
POST /api/pd/requests/{req_id}/archive
POST /api/pd/requests/{req_id}/restore
```

Payload:

```json
{
  "reason": "Solicitacao aberta por engano"
}
```

Regras:
- `APPROVED` e `COMPLETED` nao podem ser arquivados;
- archive/restore replica os campos de governanca em `pd_cards` vinculados;
- DELETEs existentes permanecem disponiveis e inalterados nesta fase.
