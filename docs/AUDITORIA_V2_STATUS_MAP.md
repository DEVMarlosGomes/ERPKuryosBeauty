# Auditoria V2 - Status Map

## CRM

Clientes (`crm_clients.stage`):
- `prospeccao`
- `qualificado`
- `projeto_em_discussao`
- `negociacao`
- `cliente_fechado`
- `cliente_perdido`

Projetos (`crm_projects.stage`):
- `projeto_em_discussao`
- `amostra_solicitada`
- `amostra_em_desenvolvimento`
- `amostra_enviada`
- `em_negociacao`
- `pedido_aprovado`
- `projeto_arquivado`

Amostras (`crm_samples.stage` / variacoes):
- `solicitada`
- `em_elaboracao`
- `retrabalho`
- `enviada`
- `aprovada`
- `reprovada`

Resultado do cliente:
- `aprovada`
- `retrabalho`
- `arquivado`
- `reprovada` legado, normalizado para `arquivado`

## P&D

Requisicoes (`pd_requests.status`):
- `OPEN`
- `IN_PROGRESS`
- `IN_TESTS`
- `WAITING_APPROVAL`
- `APPROVED`
- `COMPLETED`
- `REJECTED`

Kanban P&D (`pd_cards.status`):
- `solicitado`
- `em_desenvolvimento`
- `em_testes`
- `aguardando_aprovacao`
- `retrabalho_interno`

## Kickoff/CGI

Kickoff (`kickoffs.status`):
- `em_preenchimento`
- `aguardando_aprovacao`
- `aprovado`
- `em_revisao`
- `substituida`
- `arquivado`

Contratos (`contratos.status` observado):
- `gerado`

Pedido CGI (`orders.cgi_status`):
- `pendente`
- `assinado`

## Pedidos

Pedidos (`orders.status`):
- `rascunho`
- `confirmado`
- `em_producao`
- `concluido`
- `cancelado`

Confirmacao cliente:
- `pendente`
- `aprovado`

Aprovacao comercial:
- `nao_necessaria`
- `pendente`
- `aprovada`
- `rejeitada`

## SKU

SKUs (`skus.status`):
- `ativo`
- `descontinuado`

Campos de governanca:
- `codigo_interno`: formato CAT3-CLI4-SEQ4
- `pd_concluido`
- `amostra_id`
- `amostra_variacao_id`
- `produto_pai_id`
