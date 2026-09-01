# Auditoria V2 - Decisoes Pendentes

## DEC-001 - CGI antes ou depois do SKU

Status: revisado por decisao operacional em 2026-08-31

O DOCX de 2026-08-25 definia CGI antes de SKU. Em 2026-08-31, a regra operacional foi ajustada: assim que a amostra/variacao for aprovada pelo cliente, o sistema deve gerar SKU para que o pedido de venda em negociacao ja seja autopreenchido.

Fluxo decidido:

`Cliente -> Projeto -> Solicitacao de Amostra -> Amostra CRM -> Card P&D -> Desenvolvimento -> Formula -> Testes -> Estabilidade -> Aprovacao Interna -> Entrega ao Comercial -> Aprovacao do Cliente -> Produto-Pai -> SKU -> Pedido em negociacao -> CGI -> Pedido confirmado`

Diretriz tecnica aplicada:
- SKU nasce depois de aprovacao externa da amostra/variacao.
- SKU continua exigindo cliente com CLI4, categoria CAT3 ativa e projeto existente.
- CGI nao bloqueia a criacao do SKU.
- CGI permanece como gate posterior do pedido antes de `confirmado`.
- A API oficial de assinatura de contrato segue valida para registrar usuario, timestamp, historico e audit log.

## DEC-002 - Quem aprova P&D pelo Comercial

Status: pendente

`pd_routes.transition_status` permite aprovacao comercial de P&D para `admin`, `vendedor`, `sales_ops` e `sucesso_cliente`. A auditoria pede maker-checker mais forte.

Proposta: restringir aprovacao/reprovacao comercial a `sales_ops`, `gestor` e `admin`, mantendo `vendedor` apenas para visualizar/solicitar.

## DEC-003 - Confirmacao do cliente

Status: pendente

O sistema atual envia/filera e-mail via `email_logs` e permite aprovacao interna manual por `/orders/{id}/aprovar-cliente`. Nao ha link/token publico de confirmacao pelo cliente.

Decisao necessaria: confirmacao externa assinada por token ou etapa manual auditada pelo Comercial.

## DEC-004 - Produto-Pai nao bloquear SKU

Status: pendente

Hoje a criacao do SKU nao falha se o vinculo ao Produto-Pai falhar; o erro e registrado no log. A auditoria pede rastreabilidade forte de Produto-Pai/apresentacao.

Proposta: em P0, criar script de integridade e alerta; em P1, bloquear novo SKU sem Produto-Pai quando a tela/operacao estiver estavel.
