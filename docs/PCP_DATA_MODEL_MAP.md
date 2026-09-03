# PCP Data Model Map - FASE 0

Este mapa nao exige renomear colecoes imediatamente. Ele define contratos de dominio que o ERP deve cumprir.

## Entidades alvo

| Entidade alvo | Colecao/rota ERP atual provavel | Campos criticos |
| --- | --- | --- |
| `sales_orders` | `orders` | `id`, `tenant_id`, `numero_pedido`, `cliente_id`, `status`, `confirmacao_cliente`, `cgi`, `source_type`, `source_id`. |
| `sales_order_items` | itens dentro de `orders` hoje | `id`, `order_id`, `sku_id`, `descricao`, `qtd_total`, `qtd_planejada`, `qtd_confirmada_pcp`, `saldo`, `status`. |
| `pcp_allocations` | nova ou embutida em `pcp_programacao` | `order_item_id`, `op_id`, `qtd_reservada`, `qtd_consumida`, `status`, `created_by`. |
| `production_orders` | `ops` | `id`, `numero_op`, `order_id`, `order_item_id`, `sku_id`, `qtd_planejada`, `qtd_produzida`, `status`, `pcp_confirmed_by`. |
| `production_order_events` | novo/eventos em `ops` | `op_id`, `tipo`, `payload`, `created_at`, `created_by`, `tenant_id`. |
| `production_pointings` | apontamentos em `ops` hoje | `op_id`, `setor`, `qtd_produzida`, `turno`, `horario`, `observacoes`, `created_by`. |
| `downtime_events` | pausas/perdas em `ops` hoje | `op_id`, `linha_id`, `motivo`, `inicio`, `fim`, `duracao_min`, `responsavel`. |
| `setup_events` | novo/parcial em `pcp_programacao` | `op_id`, `linha_id`, `tipo`, `planejado_min`, `real_min`, `inicio`, `fim`. |
| `line_schedules` | `pcp_programacao` | `op_id`, `linha_id`, `data_inicio`, `data_fim`, `tipo`, `status`, `qtd_planejada`. |
| `production_lines` | `pcp_linhas` | `id`, `nome`, `codigo`, `tipo`, `capacidade`, `setup_minutos`, `status`. |
| `shifts` | `pcp_calendario`/settings | `linha_id`, `data_inicio_vigencia`, `dias_semana`, `inicio`, `fim`, `pausas`, `ativo`. |
| `day_closings` | novo/derivado dashboard | `data`, `linha_id`, `status`, `pendencias`, `closed_by`, `closed_at`. |
| `pcp_alerts` | notificacoes/novo | `tipo`, `op_id`, `linha_id`, `severity`, `status`, `last_sent_at`. |
| `pcp_settings` | settings tenant | `tolerancia_inicio_min`, `repique_alerta_min`, `setup_default_min`, `workdays`. |

## Invariantes

- Todo documento operacional tem `tenant_id`.
- Toda mutacao critica registra `created_by` ou `updated_by`.
- Soft delete usa `is_deleted`, `deleted_at`, `deleted_by`, `deleted_reason`.
- OP nao pode planejar quantidade acima do saldo do item sem override auditado.
- Status final de OP exige acao PCP, nao percentual ou fechamento da producao.
- Eventos de apontamento, parada e setup devem preservar historico; ajuste retroativo deve gerar evento corretivo.

## Indices recomendados

- `orders`: `(tenant_id, status)`, `(tenant_id, cliente_id)`, `(tenant_id, numero_pedido)`.
- `ops`: `(tenant_id, status)`, `(tenant_id, order_id)`, `(tenant_id, order_item_id)`, `(tenant_id, numero_op)`.
- `pcp_programacao`: `(tenant_id, linha_id, data_inicio)`, `(tenant_id, status)`, `(tenant_id, op_id)`.
- `production_order_events`: `(tenant_id, op_id, created_at)`.
- `pcp_alerts`: `(tenant_id, status, tipo, last_sent_at)`.

