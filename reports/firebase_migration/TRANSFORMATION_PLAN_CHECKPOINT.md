# FIREBASE -> ERP TRANSFORMATION PLAN CHECKPOINT

Data: 2026-09-24

## Estado

- Plano: `e5669507-b321-5187-96fa-7246cc909085`.
- Ambiente alvo: somente homologação.
- Status: `PLAN_ONLY_NOT_APPLIED`.
- Escritas autorizadas na homologação: não.
- Escritas permitidas na produção: não.
- Alterações no código funcional do ERP: nenhuma.
- Registros avaliados no manifesto: 3.923.

## Disposição planejada

- 3 registros: somente vínculo (`NO_OP_MAP_ONLY`), sem atualização do documento existente.
- 439 registros: inserção proposta, ainda dependente de revisão humana.
- 453 registros: bloqueados por dependências.
- 3.028 registros: bloqueados por conflito ou revisão manual.

## Ondas

1. Baseline, snapshot, manifesto e teste de restauração.
2. Clientes: 3 vínculos sem escrita e 56 inserções propostas.
3. Fornecedores: 383 inserções propostas; 6 conflitos e 14 CNPJs ausentes/inválidos bloqueados.
4. Materiais/fragrâncias: 939 bloqueados até classificação humana.
5. SKUs, fórmulas e BOM: bloqueados; nenhuma geração automática de SKU.
6. Pedidos e OPs: bloqueados por cliente, SKU, CGI e demais dependências.
7. Estoque/WMS/CQ: bloqueado até corte e conferência física.

## Reversibilidade obrigatória antes de qualquer aplicação

- Novo `mongodump` integral da homologação, mantido até a homologação final.
- SHA-256 e tamanho do snapshot registrados no manifesto.
- Contagem, hash e índices por coleção registrados como baseline.
- Teste de restauração em banco descartável antes da primeira onda.
- IDs UUIDv5 determinísticos e marcação de cada documento por plano/operação.
- Transação em lotes limitados, com parada imediata em qualquer divergência.
- Antes e depois registrados para documentos e contadores.
- Rollback seletivo somente se o hash posterior não tiver sofrido edição humana.
- Restauração integral em banco limpo caso o rollback seletivo não possa ser provado.

## Decisões ainda necessárias

- Etapa inicial dos 56 clientes legados no CRM.
- Aprovação dos 383 fornecedores elegíveis e tratamento dos 20 bloqueados/conflitantes.
- Aprovação separada de cada onda; este plano não autoriza aplicação.

