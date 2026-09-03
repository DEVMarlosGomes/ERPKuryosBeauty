# PCP Legacy Not Ported - FASE 0

Itens do PCP-Kuryos que nao devem ser portados para o ERP como implementacao direta.

| Item | Motivo |
| --- | --- |
| Firebase Realtime Database como backend | ERP usa FastAPI/MongoDB; Firebase e apenas referencia historica. |
| `database.rules.json` como fonte executavel | Regras devem virar RBAC/validadores backend. |
| `auth_check.js` montando permissao critica no frontend | Permissao no frontend e insuficiente para seguranca. |
| Watchers que alteram status em page-load | Risco de corrida, sobrescrita e mutacao invisivel. |
| Auto conclusao por percentual visual, inclusive 95% | Conclusao deve ser estado explicito confirmado pelo PCP. |
| UI de `horizonte.html` como clone literal | V21 manda extrair regra, nao copiar tela. |
| Importacao semanal como operacao principal | Usuario pediu remover; planejamento deve ser dinamico. |
| Planilhas como fonte primaria operacional | Podem ajudar migracao, mas nao ser fonte de verdade. |
| HTML monolitico legado | ERP deve manter React/Tailwind/shadcn/Radix. |
| Campos texto quando existe entidade/ID | Evitar duplicidade e orfaos. |
| RH legado no escopo PCP | Requer decisao separada. |
| Scripts `.DEPRECATED` | Classificar apenas; nao portar. |

