# PCP Domain Map - FASE 0

## Fluxo alvo

`CRM -> P&D -> SKU -> Proposta -> CGI -> Pedido -> Planejamento -> OP -> Apontamento -> PCP confirma -> Fechamento -> KPIs`

## Fronteiras de dominio

| Dominio | Responsabilidade | Fontes/rotas ERP atuais | Ajuste necessario |
| --- | --- | --- | --- |
| CRM/P&D | Origem tecnica/comercial da amostra e aprovacao. | `crm_routes.py`, `pd_routes.py`, `CRM3Page`, `PDPage`. | Amostra aprovada deve gerar SKU imediatamente e alimentar pedido em negociacao. |
| Produto/SKU | Identidade do produto acabado e variantes. | `produtos_routes.py`, `cadastros_master_routes.py`, `SKUsPage`, `CadastrosPage`. | CRUD governado, regra SKU por categoria, imutabilidade apos uso. |
| Pedido comercial | Pedido confirmado e itens que viram demanda PCP. | `orders_routes.py`, `OrderGeneratorPage`, `OrdersPage`. | Remover duplicidade cliente, puxar dados completos, item cadastrado vs digitado. |
| Planejamento PCP | Converter demanda em agenda real por linha/turno. | `pcp_routes.py`, `PCPClonePage`. | Quantidades, OPs, capacidade dinamica e sem importacao semanal. |
| OP | Execucao fisica por lote/ordem. | `orders_routes.py` (`ops_router`), `OPPage`, `OPDetail`. | Pedido -> N OPs, saldo por item, status final com confirmacao PCP. |
| Apontamento | Registro por setor/perfil. | `PCPProductionPage`, `/api/ops/{id}/apontar`, pausa, perda. | Separar fechamento operacional da conclusao PCP. |
| Estoque/WMS | Reserva, empenho, consumo e disponibilidade. | `estoque_routes.py`, `RecebimentoPage`, `EstoquePage`. | Empenho por OP e bloqueio de material nao liberado. |
| Compras/MRP | Suprir demanda real. | `compras_routes.py`, `Compras*.js`. | MRP contra demanda PCP/pedidos e fornecedor/material unico. |
| Qualidade | Gates transversais. | `cq_routes.py`, recebimento, OP. | Travas bloqueantes, nao apenas informativas. |
| Logistica/Faturamento | Expedicao, NF e contas a receber. | `LogisticaPage`, `FaturamentoPage`, `ExpedicaoPage`. | Fechar ciclo apos liberacao final e expedicao. |

## Regras de integracao

- A fonte de verdade de saldo planejado deve ser o item do pedido, nao a OP.
- A OP consome uma quantidade planejada do item; varias OPs podem atender o mesmo item.
- Uma OP avulsa so existe com permissao explicita e motivo auditado.
- Apontamento de producao atualiza produzido/eventos, mas nao conclui OP de forma final.
- Confirmacao PCP e uma transicao separada, com usuario, horario, divergencia e justificativa.
- Eventos operacionais devem ser append-only sempre que possivel.
- Toda regra critica deve existir no backend; React apenas apresenta estados e bloqueios.

