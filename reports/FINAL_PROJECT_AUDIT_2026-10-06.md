# Auditoria final do projeto — 06/10/2026

## Parecer executivo

**Decisão: NO-GO para publicação/cutover operacional.**

O frontend compila e a carga histórica do Firebase está íntegra como arquivo de revisão. Entretanto, o backend atual não passa pelo startup da suíte, a decisão do CQ ainda não é atômica, há dados filhos de P&D sem isolamento por tenant e quase toda a migração permanece deliberadamente bloqueada para revisão humana. Promover agora criaria risco de inconsistência de estoque, fabricação com fórmula incompleta, duplicidade contratual e perda de rastreabilidade.

Esta auditoria foi executada em modo somente leitura sobre a HML e sobre o worktree local. **Produção não foi acessada nem alterada.**

## Evidências validadas

- Migração histórica: 5.234 revisões; 0 IDs duplicados; 0 identidades de origem duplicadas.
- Integridade: 5.234/5.234 hashes `source_payload_sha256` conferidos; 0 ausentes e 0 divergentes.
- Estado: 5.231 registros bloqueados/não operacionais e 3 registros de RH promovidos.
- Frontend: build Vite concluído, 2/2 testes existentes aprovados.
- Python: `py_compile` e `pip check` aprovados.
- Git: `git diff --check` sem erro de whitespace, apenas avisos de normalização CRLF/LF.
- Dependências frontend: 0 críticas e 7 altas no `npm audit --omit=dev`.
- Snapshots: 16/16 arquivos referenciados existem e os SHA-256 conferem.
- Feature flags HML `pcp_material_picking_v2` e `pcp_quantity_planning_v2`: ativas.

## P0 — bloqueios críticos

### 1. O backend novo pode não iniciar

A suíte coletou 514 testes, mas encerrou com **235 erros de setup e 279 ignorados**. A causa raiz é a criação de índice composto `unique + sparse` em `(tenant_id, ra_id)`: documentos legados com `ra_id: null` entram no índice porque `tenant_id` existe, produzindo `DuplicateKey`.

Locais afetados:

- `backend/cq_routes.py:445-447` — RNC por RA;
- `backend/cq_routes.py:455-457` — retenção por RA;
- `backend/cq_routes.py:470-472` — status de lote por RA/status.

Correção necessária: preflight dos dados, saneamento controlado e índices únicos com `partialFilterExpression` que só incluam `ra_id` válido. A migração de índice precisa ser versionada, testada e reversível.

### 2. Aprovação do CQ continua não transacional

Foi adicionado um proxy de sessão, mas não existe chamada a `start_session`, `start_transaction` ou ativação do `ContextVar`. A rota ainda grava sequencialmente RA, status de lote, item, recebimento, saldo, palete, ledger, retenção/RNC, tarefas e auditoria.

Risco: falha intermediária encerra o RA, deixa o físico divergente e a repetição recebe 409 por RA já encerrado.

Também existem filtros finais somente por `id` em `backend/cq_routes.py:1328`, `:1399`, `:1428` e `:1467`, sem `tenant_id`.

### 3. Novo isolamento por tenant torna 1.147 documentos P&D invisíveis

Na HML existem:

- 663 `pd_formula_items` sem `tenant_id`;
- 391 `pd_request_status_history` sem `tenant_id`;
- 88 `pd_samples` sem `tenant_id`;
- 5 `pd_lab_results` sem `tenant_id`.

Os 663 itens apontam para fórmulas válidas, mas o código novo passou a exigir `tenant_id`. Sem backfill idempotente e verificado antes do deploy, os itens desaparecem de listagem, custo e homologação, bloqueando as fórmulas como vazias.

### 4. Fórmulas e BOMs ainda não estão prontos para fabricação

- 166 fórmulas e 663 itens;
- 36 fórmulas vazias;
- 38 fórmulas não vazias com soma diferente de 100%;
- apenas 92 fórmulas somam 100%;
- 443 revisões de fórmula/BOM bloqueadas;
- 0 produtos-pai, 0 `bom_items` e 0 versões operacionais de BOM;
- 9 solicitações de BOM em `pendente_cadastro`, todas sem `material_id`.

A promoção de estrutura também precisa validar homologação operacional de matéria-prima e fornecedor, não apenas reconciliação técnica.

### 5. Não existe lastro para homologar o ciclo físico completo

Na HML há 1 OP concluída sem `empenho_status` e sem `wms_separacao_id`. Estão zerados: recebimentos, saldos por lote, ledger, paletes, separações, conferências de PA, expedições, devoluções, retrabalho e faturamento. Há 1 RA rascunho e 1 status CQ ligados a lote sem saldo/lote operacional.

Portanto, recebimento → CQ → WMS → empenho → consumo → PA → faturamento → expedição ainda não foi comprovado em Mongo persistente.

### 6. Rastreabilidade comercial e contratual incompleta

- 16 pedidos, todos sem `client_card_id` e sem `kickoff_id`;
- 15 pedidos em rascunho e 1 concluído;
- 2 CGIs com o mesmo Kickoff/versão, ambos sem `client_id` e ainda `gerado`;
- 382/382 SKUs classificados como legado autorizado/sem CGI;
- todos os 382 sem `projeto_id`, `produto_pai_id` e `formula_vinculada`.

Esses SKUs não devem ser promovidos automaticamente para fabricação.

### 7. Migração operacional permanece fechada

Somente 3 registros de RH estão promovidos. Os demais 5.231 têm `operational_eligible=false` e `activation_status=bloqueado`. Isso é coerente com o modelo de revisão e precisa permanecer assim até decisão setorial registrada.

### 8. Plano de rollback/checkpoint está contraditório

`ROLLBACK_PLAN_CURRENT.json` ainda indica `PLAN_ONLY_NOT_APPLIED`, embora várias ondas estejam marcadas como aplicadas na HML. `MASTER_DATA_REVIEW_VERIFY.json` está `FAILED` por drift posterior em Kickoffs e `system_status`.

É necessário gerar um manifesto consolidado pós-aplicação, rebaseline controlado e todos os `VERIFY` verdes antes do checkpoint final.

### 9. Deploy não é reproduzível

- 24 arquivos modificados e 223 não rastreados;
- o diff funcional atual tem aproximadamente 2.825 inserções;
- componentes frontend, testes, scripts e evidências essenciais ainda estão fora do Git;
- `render.yaml` referencia `requirements.txt` na raiz, mas o arquivo está em `backend/requirements.txt`;
- o `DB_NAME` do manifesto diverge do banco produtivo informado;
- o frontend é Vite, mas `frontend/vercel.json` ainda declara configuração de CRA.

Sem commit/tag limpo, o deploy baseado no HEAD não reproduz o sistema testado localmente.

### 10. Segurança de sessão no refresh

O login aplica política de cookie por ambiente, mas `/auth/refresh` recria o access cookie com `secure=False` e `samesite=lax` fixos (`backend/server.py:473-487`). Isso reduz a segurança e pode quebrar autenticação cross-site. O refresh precisa usar o mesmo helper/política do login, rotação e revogação.

## P1 — alta prioridade

### Dados e cadastros

- 383 fornecedores, todos com homologação `nao_iniciada`;
- 647 materiais e 199 fragrâncias sem fornecedor operacional;
- 529 referências legadas a fornecedor: 462 resolvidas por ID e 67 ocorrências/20 IDs não resolvidos;
- clientes: 3 grupos/7 registros com nome normalizado repetido, mas sem CNPJ duplicado;
- fornecedores: 8 grupos/18 por razão social e 4 grupos/8 por nome fantasia, sem CNPJ duplicado;
- nomes semelhantes são candidatos à revisão, não autorização para merge automático.

### Multi-tenant e índices

- filtros finais sem `tenant_id` persistem em mutações de estoque, faturamento, PCP e pedidos;
- `pd_formulas`/`pd_formula_items` não possuem índices compostos por tenant;
- pedidos não possuem unicidade forte por número/ID no tenant;
- OPs não possuem índices adequados para identidade e consulta operacional.

### RBAC setorial

Leitura e mutação das filas legadas reutilizam conjuntos de papéis amplos. Cadastros aceita papéis de leitura e Qualidade inclui papéis comerciais/compras para ações. Separar permissões `READ`, `WRITE` e `APPROVE`, e ocultar/desabilitar ações no frontend conforme capabilities retornadas pelo backend.

### Propagação CQ → WMS para legado

O filtro novo por `cq_lote_id`/recebimento evita alterar lotes errados, mas um teste isolado falha porque saldos legados só têm `item_id`. É preciso migração dos vínculos e comportamento explícito de compatibilidade; não voltar ao filtro amplo por item.

### Trilha de auditoria

Há mutações em estoque, faturamento, expedição, PCP, recebimento e retrabalho sem evento imutável padronizado com `before`, `after`, ator, tenant, correlação e idempotência. Regenerar duplicatas de faturamento ainda remove fisicamente abertas/vencidas; deve cancelar/versionar.

### Testes e isolamento

`conftest.py` usa `os.environ.setdefault` para `MONGO_URL` e `DB_NAME`; portanto, pode herdar conexão externa. A suíte desta auditoria usou o banco de teste configurado externamente e falhou já no startup. O harness deve recusar hosts não descartáveis e exigir URI explícita de teste.

Em execução isolada, 234 testes passaram e 1 falhou na compatibilidade CQ/WMS, mas isso não substitui a suíte padrão nem o teste HTTP/E2E persistente.

### Runtime local

As portas 3000 e 8000 estão abertas e o shell frontend responde 200. O processo backend, porém, foi iniciado antes das mudanças atuais, não possui endpoint de health/readiness e seus schedulers registram falha recente de DNS/seleção do Atlas. Assim, porta aberta não comprova banco saudável nem o boot do código novo.

## P2 — qualidade e manutenção

- 7 vulnerabilidades npm altas na cadeia Tailwind/chokidar/braces/micromatch/source-map-js;
- somente 1 arquivo/2 testes frontend; nenhum E2E dos novos fluxos de revisão;
- 279 testes backend ignorados;
- `window.prompt` ainda existe em telas operacionais de CQ/PCP;
- tratamento de `error.response.data.detail` ainda pode enviar objeto diretamente ao toast e repetir o erro React “Objects are not valid as a React child”;
- não há pipeline CI obrigatório, canary, health/readiness ou observabilidade centralizada;
- política de senha, rate limit/lockout, MFA administrativo e revogação de refresh precisam ser formalizados;
- relatórios de migração contêm dados empresariais/identificáveis e precisam de política de acesso, retenção e sanitização;
- snapshots estão somente em armazenamento local; copiar para cofre externo e executar restore drill final;
- limpar logs e artefatos temporários e padronizar EOL.

## Prontidão por setor

| Setor | Total | Promovidos | Em revisão | Situação |
|---|---:|---:|---:|---|
| PCP | 2.071 | 0 | 0 | bloqueado |
| Logística | 1.338 | 0 | 0 | bloqueado |
| Comercial | 572 | 0 | 0 | bloqueado |
| Cadastros | 343 | 0 | 0 | bloqueado |
| Expedição | 338 | 0 | 1 | bloqueado; 1 revisão iniciada |
| Qualidade | 270 | 0 | 0 | bloqueado |
| P&D | 197 | 0 | 0 | bloqueado |
| Compras | 53 | 0 | 0 | bloqueado |
| Administração/TI | 36 | 0 | 0 | bloqueado |
| RH | 16 | 3 | 0 | promoção parcial |

A divergência do auditor de roteamento em Expedição é falso positivo: o documento continua no setor correto e apenas mudou legitimamente de `pendente` para `em_revisao`.

## Ordem obrigatória para chegar ao GO

1. Corrigir índices CQ com índice parcial, preflight e migração reversível.
2. Tornar a decisão CQ integralmente transacional e idempotente; adicionar testes de falha em cada etapa/retry.
3. Fazer backfill verificado de `tenant_id` nos 1.147 filhos P&D antes de ativar o novo scoping.
4. Sanear fórmulas vazias/percentuais, homologar MPs/fornecedores e concluir BOMs pendentes.
5. Corrigir pedidos/CGIs/SKUs legados e garantir unicidade contratual por Kickoff/versão.
6. Executar ciclo físico completo em banco persistente descartável, com ledger e reconciliação final.
7. Separar RBAC de leitura/escrita/aprovação e fechar filtros por tenant.
8. Consolidar rollback/checkpoints e deixar todos os `VERIFY` verdes.
9. Versionar todos os arquivos necessários, limpar o worktree e criar commit/tag de release.
10. Corrigir manifesto Render/Vercel, cookies de refresh e segredos/senhas HML.
11. Rodar suíte backend sem erros/skips críticos, E2E frontend e restore drill.
12. Promover por lote pequeno e por setor, nunca em massa, com reconciliação e rollback após cada onda.

## Critério mínimo de aprovação

O projeto só deve receber **GO** quando: backend iniciar em banco com legado; suíte limpa em banco descartável; ciclo HTTP/E2E integral aprovado; zero fórmula operacional vazia/inválida; CQ/estoque transacionais; todos os `VERIFY` verdes; RBAC/tenant aprovados; manifesto reproduzível; backup externo restaurado com sucesso; e cada setor assinar formalmente sua fila antes da promoção.
