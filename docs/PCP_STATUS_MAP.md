# PCP Status Map - FASE 0

## Pedido comercial

| Estado alvo | Origem comum | Significado | Pode gerar OP? |
| --- | --- | --- | --- |
| `rascunho` | Pedido em criacao. | Dados ainda editaveis. | Nao. |
| `aguardando_confirmacao_cliente` | Pedido enviado ao cliente. | Pendente aceite do cliente. | Nao, salvo override formal. |
| `confirmado` | Cliente confirmou e regras comerciais resolvidas. | Demanda valida para PCP. | Sim. |
| `em_producao` | Ao menos uma OP ativa/executada. | Pedido em atendimento. | Sim, respeitando saldo. |
| `concluido` | Todos itens atendidos e confirmados. | Pronto para expedicao/faturamento. | Nao. |
| `cancelado` | Encerrado sem produzir. | Nao operacional. | Nao. |

## Item do pedido

| Estado alvo | Regra |
| --- | --- |
| `pendente_planejamento` | Item confirmado, sem alocacao/OP suficiente. |
| `parcialmente_planejado` | Parte do saldo tem OP/alocacao. |
| `planejado` | Quantidade total coberta por OPs/alocacoes abertas. |
| `em_producao` | Alguma OP do item em execucao. |
| `aguardando_confirmacao_pcp` | OPs fechadas pela producao, pendentes PCP. |
| `atendido` | Quantidade confirmada pelo PCP cobre o item. |
| `cancelado` | Item cancelado com motivo. |

## OP

| Estado legado | Estado ERP atual encontrado | Estado alvo | Regra |
| --- | --- | --- | --- |
| `Aberta` | `aberta` | `aberta` | OP emitida, ainda nao iniciou. |
| `Em Processo` | `em_processo` | `em_producao` | Producao iniciou. |
| `Pausada` | `pausada` | `pausada` | Parada ativa com motivo. |
| `Fechada na linha` | `aguardando_confirmacao_pcp` | `aguardando_confirmacao_pcp` | Producao encerrou operacao, PCP precisa conferir. |
| `Concluido` | `concluida` | `concluida` | Apenas PCP confirma conclusao final. |
| `Cancelado` | `cancelada` | `cancelada` | Requer motivo e permissao. |

Transicao obrigatoria:

`aberta -> em_producao -> aguardando_confirmacao_pcp -> concluida`

Transicoes auxiliares:

- `em_producao -> pausada -> em_producao`
- `aberta|em_producao|pausada -> cancelada` com permissao/motivo
- `aguardando_confirmacao_pcp -> em_producao` somente se PCP reprovar fechamento e devolver para retrabalho operacional

## Slot de planejamento

| Estado atual | Estado alvo | Observacao |
| --- | --- | --- |
| `planejado` | `planejado` | Reserva horario/capacidade. |
| `em_execucao` | `em_execucao` | Deve refletir OP em producao, nao substituir OP. |
| `concluido` | `executado` | Slot executado nao conclui OP sozinho. |
| `cancelado` | `cancelado` | Motivo e auditoria. |

## Lote/material

| Estado alvo | Regra |
| --- | --- |
| `recebido` | Material chegou, ainda nao disponivel. |
| `conferencia` | Quantidade/documento em conferencia. |
| `quarentena` | Aguardando qualidade. |
| `liberado` | Disponivel para WMS/empenho. |
| `rnc_aberta` | Bloqueado por nao conformidade. |
| `devolucao` | Fluxo de devolucao. |
| `retrabalho` | Tratamento definido. |
| `enderecado` | Posicionado no WMS. |
| `empenhado` | Reservado para OP. |
| `consumido` | Baixado por OP. |
