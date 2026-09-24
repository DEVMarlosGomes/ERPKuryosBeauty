# FIREBASE -> ERP HOMOLOGATION RECONCILIATION CHECKPOINT

Data: 2026-09-24

## Escopo validado

- Fonte Firebase: SHA-256 `7b6ba88ff260d4b8c18e4a057e9e6732d77d394c88d4b4bd034e08a7fe0b83e4`.
- ERP alvo: `kuryos_erp_homologacao`.
- Tenant aprovado: `a1534e89-bbfa-483f-ac0b-8d6dbf6bab22` (`Kuryos Demo`).
- Modo da reconciliação: somente leitura.
- Escritas Mongo durante a reconciliação: nenhuma.
- Banco de produção: não alterado; credencial limitada a `read@kuryos`.
- Homologação após reconciliação: 101 coleções e 9.041 documentos, sem alteração em relação ao clone validado.

## Classificações

- `MATCH`: 3.
- `INSERT_CANDIDATE`: 906.
- `MERGE_CANDIDATE`: 0.
- `CONFLICT`: 6.
- `MANUAL_REVIEW`: 3.008.
- `SKIP`: 0.

## Filas por domínio

- Clientes: 3 matches e 56 candidatos de inserção.
- Fornecedores: 397 candidatos de inserção e 6 registros em conflito, correspondentes a CNPJs duplicados na fonte.
- Materiais: 939 em revisão manual; cadastro alvo vazio e classificação de domínio pendente.
- SKUs e aliases: 392 em revisão manual; geração automática permanece proibida.
- Pedidos: 453 candidatos de inserção, dependentes de cliente, SKU e CGI reconciliados.
- OPs: 1.388 em revisão manual; apontamentos históricos não serão reproduzidos.
- Endereços: 250 em revisão manual e dependentes de conferência física.
- Lotes: 39 em revisão manual e dependentes de material, endereço, CQ/WMS e corte físico.
- Fórmulas: 197 pendentes das decisões de materiais.
- BOMs: 246 pendentes de produto pai, SKU e materiais; camadas bulk e embalagem devem permanecer separadas.

## Estoque

- `estoque.saldoAtual` não será usado como saldo inicial.
- Movimentos históricos não serão reproduzidos.
- O corte inicial depende de lotes físicos, CQ/WMS e conferência física.
- Permanecem 44 saldos agregados negativos, 150 movimentos com sinal ambíguo e 268 referências órfãs para revisão.

## Gate atual

Nenhuma transformação final foi gerada e nenhum dado Firebase foi aplicado ao ERP. Antes disso são obrigatórios:

1. revisar os 6 conflitos de fornecedores;
2. aprovar a política de cadastro dos 939 materiais e 392 SKUs/aliases;
3. decidir o tratamento dos 56 clientes e 397 fornecedores candidatos;
4. manter estoque, OPs, lotes, fórmulas e BOMs bloqueados até resolver suas dependências;
5. autorizar explicitamente a geração do plano de transformação para homologação.

