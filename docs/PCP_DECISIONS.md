# PCP Decisions - FASE 0

## Decisoes ja tomadas

| ID | Decisao | Impacto |
| --- | --- | --- |
| DEC-PCP-001 | O ERP e a fonte alvo. O PCP-Kuryos e referencia comportamental, nao arquitetura. | Nao copiar Firebase/HTML. |
| DEC-PCP-002 | Importacao de programacao semanal nao deve ser fluxo operacional. | Remover/ocultar UI de importacao e planejar direto no ERP. |
| DEC-PCP-003 | `horizonte.html` nao sera clonado como UI. | Extrair regras de capacidade/prioridade para UX nova. |
| DEC-PCP-004 | Producao nao conclui OP de forma final. | Criar/usar estado `aguardando_confirmacao_pcp`. |
| DEC-PCP-005 | Amostra aprovada deve gerar SKU imediatamente. | Pedido de venda em negociacao deve vir com codigo automatico quando ja existe SKU aprovado. |
| DEC-PCP-006 | OP avulsa e excecao. | Exigir permissao e motivo. |
| DEC-PCP-007 | Card delete/remocao e operacao governada. | Superuser/capability, motivo, soft delete, restore. |

## Decisoes pendentes

| ID | Pendencia | Opcao recomendada | Bloqueia |
| --- | --- | --- | --- |
| DEC-PCP-101 | Perfis finais por setor de apontamento: manipulacao, logistica, envase, rotulagem, laboratorio. | Modelar `setor` no usuario e na OP, com fallback admin/pcp. | Apontamento por setor completo. |
| DEC-PCP-102 | Regras de override para produzir sem confirmacao do cliente. | Permitir apenas superuser com motivo e auditoria. | Planejamento em urgencia. |
| DEC-PCP-103 | RH legado. | Manter fora desta consolidacao ate ordem explicita. | Nada do PCP. |
| DEC-PCP-104 | Se API de importacao de programacao fica para migracao tecnica. | Manter endpoint protegido/sem UI ate migracao terminar, depois remover. | Limpeza final. |
| DEC-PCP-105 | Tolerancias de alerta por tenant. | Comecar com 5 min inicio, 10 min repique, parametrizar em settings. | Alertas robustos. |

