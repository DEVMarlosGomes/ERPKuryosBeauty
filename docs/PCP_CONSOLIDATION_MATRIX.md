# PCP Consolidation Matrix - FASE 0

Acao permitida: `PORTAR`, `ADAPTAR`, `MANTER ERP`, `DESCARTAR LEGADO`, `DECISION_REQUIRED`, `JA EXISTE`, `BUG DO LEGADO - NAO PORTAR`.

| ID | Origem PCP | Regra/Feature | Estado no PCP | Existe no ERP? | Acao | Destino ERP | Dependencias | Risco | Teste |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| PCP-001 | `auth_check.js` | Perfis `admin`, `pcp`, `production`, `rotulagem`, `rh`, `gestor` por pagina. | UI/JS + Firebase. | Parcial. | ADAPTAR | `backend/rbac.py`, guards React. | Mapa de permissoes. | Medio: IDOR se ficar no frontend. | Testar acesso negado por rota/API. |
| PCP-002 | `database.rules.json` | Isolamento e escrita por papel. | Firebase rules. | Parcial. | ADAPTAR | Validadores FastAPI + tenant filter. | `get_current_user`. | Alto: regra critica nao pode ser React-only. | Cross-tenant e role tests. |
| PCP-003 | `pedidos.html` | Acompanhamento de pedidos ativos, saldo, linha por OP. | Funcional legado. | Parcial. | ADAPTAR | `OrdersPage`, `orders_routes.py`, `pcp_allocations`. | Pedido com SKU/CGI/confirmacao. | Alto: duplicidade de saldo. | Pedido com 2 OPs nao excede saldo. |
| PCP-004 | `emitir_op.html` | OP deve sair vinculada a pedido por padrao; avulsa so excecao com motivo. | Funcional. | Parcial. | PORTAR | `orders_routes.py create-op`, `OPPage`, planejamento PCP. | Saldo por item. | Alto: OP avulsa mascara demanda. | Bloquear avulsa sem permissao/motivo. |
| PCP-005 | `emitir_op.html` | Formula/BOM/especificacao usados na emissao. | Funcional. | Parcial. | ADAPTAR | Formula Bank, BOM, Produto/SKU, OP detail. | SKU aprovado e BOM ativo. | Alto: OP sem insumo correto. | OP sem BOM aprovado falha. |
| PCP-006 | `ops.html` | Controle visual das OPs emitidas. | Funcional. | Sim. | ADAPTAR | `OPPage`, `OPDetail`, `pcp_routes.py`. | Status map final. | Medio: status divergente. | Lista OPs por status e tenant. |
| PCP-007 | `planejamento.html` | Grade/agenda/capacidade por linha, dia, turno. | Funcional legado. | Parcial. | PORTAR | `PCPClonePage`, `pcp_routes.py`, calendario dinamico. | Linhas, turnos, capacidade. | Alto: planejamento travado. | Ajustar 2 turnos a partir de uma data futura. |
| PCP-008 | `planejamento.html` | Remover importacao semanal como fluxo principal. | Existe no legado e ERP. | Sim. | DESCARTAR LEGADO | Remover/ocultar importacao, manter API apenas se migracao exigir. | Decisao 18/08/2026. | Baixo. | UI nao exibe importacao operacional. |
| PCP-009 | `horizonte.html` | Regras de prioridade, congelamento e backlog. | Funcional, UI legado. | Parcial. | ADAPTAR | Planejamento PCP novo. | Algoritmo prioridade/capacidade. | Alto: copiar UI errada. | Horizonte calcula backlog sem layout legado. |
| PCP-010 | `form.html` | Apontamento por OP/setor, paradas, perdas e fechamento. | Funcional legado. | Parcial. | PORTAR | `PCPProductionPage`, `/api/ops/*`. | OP em execucao e perfil setor. | Alto: producao concluir indevidamente. | Fechar OP gera aguardando PCP, nao concluida. |
| PCP-011 | `dashboard.html` | Dashboard diario e fechamento do dia. | Funcional. | Parcial. | ADAPTAR | `PCPDailyDashboard`, `/api/pcp/dashboard`. | Historico e OPs aguardando. | Medio. | Dashboard bate com historico consolidado. |
| PCP-012 | `dashboard_analise.html` | KPIs PCP analiticos. | Funcional legado. | Parcial. | ADAPTAR | Relatorios/KPIs PCP. | Dados confiaveis de eventos. | Medio: KPI falso se dado incompleto. | KPI ignora dado sem fonte confiavel. |
| PCP-013 | `cadastros.html` | Cadastros operacionais. | Funcional legado. | Sim. | MANTER ERP | `CadastrosPage`, cadastros master. | Reordenacao de modulos. | Baixo. | Cadastro nao duplica fonte. |
| PCP-014 | `clientes.html` | Clientes PCP. | Funcional legado. | Sim. | MANTER ERP | CRM/Cadastros Clientes. | Deduplicacao clientes. | Medio. | Sugestao de cliente sem duplicidade. |
| PCP-015 | `produtos.html` | Produtos PCP. | Funcional legado. | Sim. | ADAPTAR | Cadastros -> Produtos e SKUs. | Regras SKU. | Alto. | SKU imutavel apos uso. |
| PCP-016 | `formulas.html` | Formula/BOM. | Funcional legado. | Parcial. | ADAPTAR | Formula Bank, P&D, BOM. | V2.1 formula links. | Alto. | Pesquisa por MP/fragrancia/cliente. |
| PCP-017 | `materiais.html` | Materiais/MPs. | Funcional legado. | Sim. | ADAPTAR | Cadastros Materiais/MPs. | Categorias MP e homologacao. | Medio. | MP homologada aparece em compras/custos/estoque. |
| PCP-018 | `compras.html` | Compras ligadas a necessidade. | Funcional legado. | Sim. | ADAPTAR | Compras/MRP ERP. | Demanda PCP real. | Alto. | MRP consome pedidos confirmados. |
| PCP-019 | `insumos.html` | Matriz de insumos/recebimento. | Funcional legado. | Parcial. | ADAPTAR | Recebimento, Estoque, WMS, BOM. | Qualidade/quarentena. | Alto. | Material recebido nao fica disponivel antes de liberar. |
| PCP-020 | `logistica.html` | Logistica operacional. | Funcional legado. | Sim. | ADAPTAR | Logistica/Expedicao/Agendamentos ERP. | Pedido e expedicao. | Medio. | Agendamento abre e filtra corretamente. |
| PCP-021 | `historico.html` | Historico/auditoria. | Funcional legado. | Parcial. | ADAPTAR | Historico PCP + audit log. | Eventos normalizados. | Medio. | Toda transicao aparece no historico. |
| PCP-022 | `public/shared/utils.js` | Normalizadores e helpers de regra. | JS compartilhado. | Parcial. | ADAPTAR | Servicos Python/React utilitarios. | Revisao regra a regra. | Medio. | Unit tests dos calculos migrados. |
| PCP-023 | `functions/index.js` | E-mails, alertas e jobs. | Cloud Functions. | Parcial. | ADAPTAR | Workers/servicos backend ERP. | Outbox/idempotencia. | Alto: disparo duplicado. | Retry nao duplica e-mail/efeito. |
| PCP-024 | `rh_*.html` | RH. | Fora do escopo PCP. | Parcial. | DECISION_REQUIRED | A definir. | Decisao de produto. | Baixo no PCP. | Nao implementar sem decisao. |
| PCP-025 | Watchers Firebase | Autoajustes globais em carga de pagina. | Legado perigoso. | Nao. | BUG DO LEGADO - NAO PORTAR | Workers explicitos/idempotentes. | Jobs backend. | Alto: corrida e sobrescrita. | Sem mutacao em page-load. |
| PCP-026 | `dashboard.html`/helpers | Percentual >= 95 tratado como concluido para visual. | Legado. | Parcial. | BUG DO LEGADO - NAO PORTAR | Status explicito somente. | Confirmacao PCP. | Alto. | 95% nao conclui OP/pedido. |
| PCP-027 | PCP dominio | Pedido -> varias OPs com saldo por item. | Funcional esperado. | Parcial. | PORTAR | `sales_order_items`, `production_orders`, `pcp_allocations`. | Data model. | Critico. | OPs somadas nao excedem qtd do item. |
| PCP-028 | PCP dominio | Status `Em Producao -> Aguardando Confirmacao PCP -> Concluida`. | Mapeado no legado. | Nao completo. | PORTAR | `/api/ops`, `/api/pcp/confirmacoes`. | RBAC PCP. | Critico. | Producao nao conclui final. |
| PCP-029 | PCP dominio | ETA com tempo produtivo = decorrido - paradas. | Funcional no legado. | Parcial. | PORTAR | Eventos OP + dashboard. | Eventos de pausa/retomada. | Medio. | ETA zero-safe e considera pausas. |
| PCP-030 | PCP dominio | Setup/changeover planejado e real. | Funcional no legado. | Parcial. | PORTAR | `setup_events`, planejamento, KPI. | Linha/SKU/OP. | Medio. | Setup real vs padrao. |
| PCP-031 | PCP dominio | Alertas de inicio atrasado e OP estourada. | Funcional no legado. | Parcial. | PORTAR | Worker + notificacoes ERP. | Calendario/slots. | Medio. | Tolerancia 5 min e repique 10 min. |
| PCP-032 | PCP dominio | Fechamento do dia como conferencia, nao digitacao redundante. | Funcional esperado. | Parcial. | PORTAR | Dashboard fechamento PCP. | Eventos confiaveis. | Medio. | Fechamento aponta pendencias. |
| PCP-033 | PCP dominio | KPIs apenas sobre dados confiaveis. | Requisito V21. | Parcial. | PORTAR | Indicadores PCP. | Historico normalizado. | Medio. | KPI marca amostra incompleta. |
| V21-001 | ERP V2.1 | Editar/remover cards com permissao, motivo e soft delete. | Requisito. | Parcial. | ADAPTAR | CRM/P&D/Pedidos/PCP + backend. | RBAC superuser. | Alto. | Usuario comum nao remove; superuser restaura. |
| V21-002 | ERP V2.1 | Formula bank pesquisavel e link formula-cliente. | Requisito. | Parcial. | PORTAR | P&D Formula Bank + Cadastros. | Indices e modelo link. | Alto. | Pesquisa e link N clientes. |
| V21-003 | ERP V2.1 | Toggle D48 por superuser e snapshot por amostra. | Requisito. | Parcial. | PORTAR | Tenant settings + P&D. | Audit log. | Alto. | Alterar toggle nao muda amostra antiga. |
| V21-004 | ERP V2.1 | Amostra aprovada gera pacote comercial. SKU deve nascer na aprovacao da amostra. | Requisito + ajuste usuario. | Parcial. | PORTAR | P&D -> SKU -> proposta/CGI/pedido. | Idempotencia por sample/version. | Critico. | Aprovar amostra 2x nao duplica SKU/pedido. |
| V21-005 | ERP V2.1 | CRUD completo de SKUs em Cadastros. | Requisito. | Parcial. | ADAPTAR | Cadastros -> Produtos e SKUs. | Categorias Produto/MP. | Alto. | SKU usado nao permite hard delete. |

