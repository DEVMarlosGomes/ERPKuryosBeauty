# Auditoria V2 - Matriz de Achados

Base: `3eefc93327dad017671763af8ff4aa2734be6922`
Branch de trabalho: `audit-v2-crm-pd-sku-orders`
Data: 2026-08-24

## Escopo

Fluxo auditado: Cliente -> Projeto -> Solicitacao de Amostra -> Amostra CRM -> Card/Requisicao P&D -> Desenvolvimento -> Formula -> Testes -> Estabilidade -> Aprovacao interna -> Entrega ao Comercial -> Aprovacao do Cliente -> Produto-Pai -> SKU -> Pedido em negociacao -> CGI/requisitos comerciais -> Pedido confirmado.

## P0

| ID | Severidade | Status | Area | Evidencia | Acao |
| --- | --- | --- | --- | --- | --- |
| V2-ORD-001 | P0 | BUG | Gerador de Pedidos | `frontend/src/pages/OrderGeneratorPage.js` mantem `cliente_id`, mas `buildPayload` nao envia. `backend/orders_routes.py::OrderCreate` nao possui `cliente_id` e `_create_order_document` aceita snapshot textual. | Exigir `cliente_id` valido no Gerador e persistir o vinculo no pedido. |
| V2-ORD-002 | P0 | BUG | Gerador de Pedidos | `applyClient` limpa apenas `cliente_id` quando o texto nao bate com cliente cadastrado; CNPJ, endereco, telefone e e-mail podem permanecer de selecao anterior. | Limpar campos derivados quando nao houver selecao inequivoca. |
| V2-SKU-001 | P0 | OK | SKU/CGI | Decisao operacional de 2026-08-31: amostra aprovada gera SKU imediatamente para alimentar pedido de venda em negociacao; CGI fica como gate posterior antes da confirmacao do pedido. | Gate de SKU ajustado para nao exigir CGI. |
| V2-SKU-002 | P0 | PARCIAL | SKU | `_create_sku_from_variacao_v2` reaproveita SKU por variacao antes de inserir, e `codigo_interno` tem indice unico. Falta indice unico em `(tenant_id, amostra_id, amostra_variacao_id)`. | Adicionar indice unico parcial/idempotente por variacao. |
| V2-ORD-003 | P0 | PARCIAL | Confirmacao Cliente | `/orders/{id}/solicitar-confirmacao-cliente` gera `email_logs` e `/aprovar-cliente` aprova internamente. Nao ha token/link externo auditavel do cliente. | Implementar confirmacao externa ou registrar decisao como etapa manual assumida. |
| V2-DATA-001 | P0 | OK | Clientes | `scripts/audit_duplicate_clients.py` audita duplicidade por CNPJ, nome normalizado e CLI4. | Rodar contra banco real e tratar findings. |
| V2-DATA-002 | P0 | OK | Materiais | `scripts/audit_material_links.py` audita vinculos MP/fornecedor entre homologacao, cadastros e estoque lab. | Rodar contra banco real e tratar findings. |
| V2-SKU-003 | P0 | OK | SKU | `scripts/audit_sku_integrity.py` audita formato, duplicidade por codigo e por variacao, cliente e Produto-Pai. | Rodar contra banco real e tratar findings. |
| V2-ORD-004 | P0 | OK | Pedidos | `scripts/audit_order_integrity.py` audita pedidos do gerador sem `cliente_id`, fingerprints duplicados e gates CGI/cliente. | Rodar contra banco real e tratar findings. |

## P1

| ID | Severidade | Status | Area | Evidencia | Acao |
| --- | --- | --- | --- | --- | --- |
| V2-PD-001 | P1 | PARCIAL | D48h | `assert_d48h_stability_ok` e chamado em transition P&D e drag/drop CRM. | Cobrir com testes dos caminhos de entrega ao Comercial. |
| V2-PD-002 | P1 | PARCIAL | Retrabalho | `resultado-cliente` salva `feedback_cliente` e `direcoes_retrabalho`; `PDPage` exibe os campos. | Testar ponta a ponta com amostra real e historico. |
| V2-PD-003 | P1 | PARCIAL | Aprovacao Comercial P&D | `pd_routes.transition_status` permite aprovacao comercial por `admin`, `vendedor`, `sales_ops`, `sucesso_cliente`. | Endurecer papeis conforme decisao operacional. |
| V2-CAD-001 | P1 | PARCIAL | Cadastros | `CadastrosPage` e `cadastros_master_routes.py` ja centralizam clientes, fornecedores, produtos, materiais e categorias. | Validar permissoes, responsividade e integracao com homologacoes. |
| V2-CAT-001 | P1 | PARCIAL | CAT3 | `categorias_routes.py` possui CRUD/aprovacao/inativacao e bloqueia CAT3 duplicado. | Garantir UI completa e uso obrigatorio no SKU. |

## Itens corrigidos antes desta fase

- D48h possui gate central em `backend/pd_routes.py`.
- Pedido Direto exige cliente e SKU existentes e valida ownership do SKU.
- P&D exibe observacoes de retrabalho no card.
- Cadastros possui abas para clientes, fornecedores, produtos, materiais e categorias.
- Pedido confirmado exige CGI assinado em `backend/orders_routes.py`.

## Itens nao reproduzidos no Discovery

- Fluxo com amostra real `2026-1018-a`.
- Confirmacao real por e-mail externo do cliente.
- Responsividade visual completa.
- Integridade de dados em Mongo real.
