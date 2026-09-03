# PCP Source Inventory - FASE 0

Fonte principal lida: `C:\Users\MARLOS\Downloads\KURYOS_ERP_V21_PCP_CONSOLIDATION_CODEX.md`.

Referencia PCP clonada localmente em `.reference/PCP-Kuryos` apenas para auditoria. A pasta foi excluida do Git local em `.git/info/exclude`.

Commit de referencia PCP: `3e968d23b351c25cb6a66c9a46376b14899b40a6`.

## Inventario PCP legado

Raiz:

| Artefato | Papel no discovery |
| --- | --- |
| `PLANO_PLANEJAMENTO_PCP.md` | Plano funcional historico do planejamento PCP. |
| `MELHORIAS_FUTURAS.md` | Backlog e decisoes futuras do sistema irmao. |
| `database.rules.json` | Regras legadas Firebase; extrair intencao de permissao, nao portar tecnologia. |
| `functions/index.js` | Automacoes, e-mails, alertas e workers legados. |
| `*.DEPRECATED` | Codigo explicitamente legado; classificar, nao portar. |
| Planilhas e HTML de exemplo | Evidencia de documento/operacao; usar como referencia de campos e calculos. |

Arquivos `public` obrigatorios mapeados:

| Arquivo | Classificacao |
| --- | --- |
| `admin.html` | Configuracoes PCP, metas, parametros e permissoes operacionais. |
| `auth_check.js` | RBAC e montagem de navegacao; portar regra para backend/RBAC ERP. |
| `cadastros.html` | Cadastros operacionais PCP. |
| `clientes.html` | Clientes legados; consolidar em CRM/Cadastros. |
| `compras.html` | Compras legadas; cruzar com Compras/MRP ERP. |
| `dashboard.html` | Dashboard diario, fechamento, metas, OPs aguardando confirmacao. |
| `dashboard_analise.html` | Indicadores analiticos de PCP. |
| `emitir_op.html` | Emissao de OP, vinculo pedido, formula/BOM, quantidade, etiqueta. |
| `form.html` | Apontamento de producao, paradas, turno, fechamento de lote. |
| `formulas.html` | Banco de formulas e BOM legado. |
| `historico.html` | Historico e auditoria operacional. |
| `horizonte.html` | Regras de horizonte/prioridade; nao copiar UI. |
| `insumos.html` | Matriz/recebimento/insumos. |
| `logistica.html` | Logistica operacional. |
| `materiais.html` | Materiais/MPs. |
| `ops.html` | Controle de OPs emitidas. |
| `pedidos.html` | Acompanhamento de pedidos comerciais no PCP. |
| `planejamento.html` | Grade, agenda, capacidade, turnos, bloqueios e limpeza de programacao. |
| `produtos.html` | Produtos legados; destino em Cadastros Produtos/SKUs. |
| `rh_*.html` | RH fora do escopo PCP; manter como decisao pendente. |
| `public/shared/utils.js` | Helpers e normalizadores de dominio; extrair regras, nao copiar acoplamento Firebase. |
| `public/shared/theme.css` | Tema legado; nao e fonte de verdade funcional. |

## Inventario ERP atual

Backend relevante:

| Arquivo | Estado encontrado |
| --- | --- |
| `backend/pcp_routes.py` | Ja possui linhas, calendario, programacao, lotes, historico, dashboard e sugestao de setup. Ainda tem importacao de programacao e transicoes que concluem OP ao concluir slot. |
| `backend/orders_routes.py` | Ja possui pedidos, confirmacao cliente/comercial, CGI, OPs e apontamentos. Precisa alinhar Pedido -> N OPs, saldo por item e confirmacao PCP final. |
| `backend/compras_routes.py` | Base de Compras/MRP existe; precisa receber demanda real do PCP/pedidos. |
| `backend/estoque_routes.py` | Base de estoque existe; precisa reserva/empenho e consumo por OP. |
| `backend/recebimento_routes.py` | Recebimento existe; precisa quarentena/gates quando aplicavel ao PCP. |
| `backend/cq_routes.py` | Qualidade existe; precisa virar gate bloqueante nas transicoes PCP. |
| `backend/produtos_routes.py` | Produtos/SKUs existem; precisa CRUD completo e imutabilidade pos uso. |
| `backend/cadastros_master_routes.py` | Modulo Cadastros existe; destino correto para produtos, clientes, fornecedores, MPs e categorias. |
| `backend/rbac.py` | Ponto correto para permissoes, superuser/capabilities e perfil PCP. |
| `backend/workflow_engine.py` | Ponto correto para transicoes e automacoes idempotentes. |

Frontend relevante:

| Arquivo | Estado encontrado |
| --- | --- |
| `frontend/src/pages/PCPDailyDashboard.js` | Dashboard PCP ja existe com UI inspirada no sistema irmao. |
| `frontend/src/pages/PCPProductionPage.js` | Apontamento por setor existe; ainda permite finalizar OP como `concluida` direto. |
| `frontend/src/pages/PCPClonePage.js` | Planejamento/horizonte consolidado; deve ser avaliado contra regras V21. |
| `frontend/src/pages/OPPage.js` / `OPDetail.js` | Controle/detalhe de OPs existem. |
| `frontend/src/pages/OrdersPage.js` / `OrderGeneratorPage.js` | Pedido comercial e gerador existem; precisam integracao final com SKU aprovado e OPs. |
| `frontend/src/pages/CadastrosPage.js` / `SKUsPage.js` | Destino para produtos/SKUs e cadastros mestre. |
| `frontend/src/pages/Compras*.js` | Compras/MRP ja existem. |
| `frontend/src/pages/EstoquePage.js` / `RecebimentoPage.js` | Estoque e recebimento ja existem. |
| `frontend/src/pages/LogisticaPage.js` / `LogisticaAgendamentosPage.js` | Logistica ja existe. |
| `frontend/src/components/Sidebar.js` | Navegacao atual ja tem PCP e Cadastros; sera base de reordenacao posterior. |

## Achados de discovery

- A referencia PCP tem regras maduras, mas esta espalhada em HTML, Firebase compat, watchers e Cloud Functions.
- O ERP ja tem modulos equivalentes. A consolidacao deve endurecer regras e fluxo, nao duplicar telas.
- A regra central deve ser Pedido confirmado com itens -> varias OPs, cada OP consumindo saldo planejado do item.
- Producao pode apontar e fechar operacao, mas conclusao final da OP deve ficar em `Aguardando confirmacao PCP` ate conferencia do PCP.
- Importacao de programacao semanal nao deve ser mantida como operacao principal, conforme observacao de 18/08/2026.
- `horizonte.html` deve fornecer regras de prioridade/capacidade, nao layout.
- RH legado deve permanecer classificado como `DECISION_REQUIRED`.

