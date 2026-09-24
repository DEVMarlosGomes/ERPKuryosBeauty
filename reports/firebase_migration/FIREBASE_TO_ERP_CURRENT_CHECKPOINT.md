# FIREBASE → ERP CURRENT CHECKPOINT

ERP HEAD: `1b1ca49add9fd59fd1798deb2ad82f0a22f55d6b` (`feature/pcp-delta-only-2026-09`), com worktree preexistente sujo registrado em `current_erp_head.json`  
Mongo DB: `kuryos_firebase_staging_current` (staging local); banco ERP alvo não fornecido e não acessado  
Tenant: não fornecido; reconciliação ERP não executada  
Source SHA256: `7b6ba88ff260d4b8c18e4a057e9e6732d77d394c88d4b4bd034e08a7fe0b83e4`

Matches: 0 — não avaliados sem Mongo/tenant alvo  
Insert candidates: 0 — não avaliados sem Mongo/tenant alvo  
Merge candidates: 0 — não avaliados sem Mongo/tenant alvo  
Conflicts: 5 grupos detectados somente na fonte; conflitos contra ERP não avaliados  
Manual review: 3.923 registros de mapas conservadores

Clientes: 59  
Fornecedores: 403  
Materiais: 939  
SKUs: 392 produtos/aliases  
Fórmulas: 197  
BOM: 246  
Pedidos: 453, sendo 76 comerciais e 377 registros PCP/pedido legado  
PCP orders: 377  
OPs: 1.388  
Compras: 20, sendo 16 pedidos e 4 solicitações  
Recebimentos: 7 operações internas em 3 agrupadores Firebase  
Estoque/lotes: 95 saldos agregados não utilizáveis como abertura; 39 lotes físicos candidatos  
CQ: 9 registros principais, sendo 2 não conformidades e 7 conferências de PA  
Expedição: 338  
RH: 16 registros principais, sendo 3 cargos e 13 usuários

Estoque negativo legado: 44  
Movimentos com sinal ambíguo: 150  
Referências órfãs: 268  
Datas suspeitas: 98

Pode gerar transform final? **NÃO**

Bloqueadores:

- URI do Mongo ERP não fornecida explicitamente.
- `DB_NAME` do ERP não fornecido explicitamente.
- `tenant_id` alvo não fornecido explicitamente.
- Fase D não foi iniciada; nenhum `find`, `aggregate`, `count` ou `listIndexes` foi executado no ERP.
- O corte físico e a decisão CQ/WMS dos 39 lotes candidatos ainda precisam de validação humana.
- Há 44 saldos agregados negativos, 150 movimentos cujo sinal não é delta contábil seguro, 268 referências órfãs e 98 datas suspeitas.
- Existem 3 grupos de CNPJ duplicado entre fornecedores e 2 colisões/aliases de SKU na fonte.

Nenhum apply de produção foi gerado. Nenhum dado foi escrito no banco ERP.
