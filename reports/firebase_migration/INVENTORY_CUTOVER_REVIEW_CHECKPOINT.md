# Corte físico de estoque legado — checkpoint HML

Data: 2026-09-25  
Status: **APLICADO E VERIFICADO SOMENTE EM HOMOLOGAÇÃO**

## Resultado

- 250 endereços WMS em revisão física.
- 39 lotes em revisão de material, endereço, CQ/WMS e saldo físico.
- Total: 289 documentos em `legacy_inventory_cutover_reviews`.
- Todos permanecem com `operational_eligible = false`, `activation_status = bloqueado`, `physical_count_confirmed = false` e `review_status = pendente_revisao`.

Nenhum saldo agregado do Firebase foi aceito como saldo inicial. Nenhum movimento histórico foi reproduzido.

## Isolamento operacional confirmado

Antes e depois da onda, as seguintes coleções permaneceram com zero documentos do tenant:

- `wms_enderecos`;
- `estoque_saldos_lote`;
- `inventory_ledger`;
- `reservas_lote`;
- `wms_paletes`;
- `estoque_movimentos_lote`;
- `wms_quarantine_movements`.

Os 289 hashes dos documentos e os 289 hashes dos payloads de origem foram verificados sem falhas.

## Snapshot e retorno

- Snapshot: `C:\Users\MARLOS\.kuryos\backups\kuryos-erp-hml-pre-inventory-cutover-review-20260925.archive.gz`
- SHA-256: `22f9e828e96ea8928a5fc48322c4ec785cd00c6464837f16b8e742fdde60406d`
- Conteúdo: 108 coleções e 13.280 documentos.
- Restauração integral: verificada; banco descartável removido.
- Rollback seletivo: verificado em banco local descartável, removendo os 289 documentos e a coleção; banco descartável removido.

## Visualização no ERP

Disponível em `Cadastros > Revisão legado > Corte físico legado`, em modo somente leitura. A tela permite filtrar endereços/lotes e consultar o payload de origem, sem botão de ativação.

## Próximo portão obrigatório

A ativação operacional deve ser outra onda e exige conferência física registrada, material resolvido, endereço validado, decisão do CQ, unidade confirmada e autorização formal do saldo inicial. Somente então poderão ser gerados saldo por lote e movimento inaugural idempotente no ledger.

Produção não foi acessada nem alterada.

## Distribuição setorial

Os 289 registros foram encaminhados sem ativação operacional:

- 250 endereços: `assigned_sector = logistica`, etapa `conferencia_endereco_wms`;
- 39 lotes: `assigned_sector = qualidade`, etapa `validacao_cq_lote_legado`, com `next_sector = logistica`.

As filas estão visíveis diretamente nos módulos:

- `Logística`: painel **Revisão legada de endereços WMS**;
- `Qualidade`: aba **Lotes legados**.

Snapshot anterior à distribuição:

- arquivo: `C:\Users\MARLOS\.kuryos\backups\kuryos-erp-hml-pre-sector-dispatch-20260925.archive.gz`;
- SHA-256: `e34091649157d57c99a1bb2058d6dafb95fdaa6d9334eb822587eee6f325c660`;
- 109 coleções e 13.569 documentos, com restauração verificada.

O rollback da distribuição foi ensaiado em banco local descartável: 289 documentos retornaram ao estado anterior, sem falhas de hash, e o banco de ensaio foi removido. A HML não possui atualmente usuários com papéis `logistica` ou `estoque`; por isso a distribuição foi feita por fila setorial, sem atribuir indevidamente os itens a administradores.

## Fluxo setorial habilitado em HML

- A Qualidade pode aprovar, reprovar ou reter cada lote legado.
- A aprovação do CQ encaminha o lote para a fila da Logística, sem criar saldo.
- A Logística pode confirmar a conferência física ou registrar divergência de endereços e lotes.
- Uma conferência confirmada altera o registro para `review_status = pronto_para_corte`, mas preserva `activation_status = bloqueado` e `operational_eligible = false`.
- A ativação de saldos e os movimentos inaugurais continuam fora desta etapa.

Validação de 2026-09-25:

- backend: 23 testes aprovados;
- frontend: compilação aprovada;
- OpenAPI HML: rotas de decisão do CQ e conferência da Logística publicadas;
- banco HML: 39 itens na Qualidade, 250 itens na Logística e zero itens prontos para corte antes da atuação humana;
- `wms_enderecos`, `estoque_saldos_lote` e `inventory_ledger`: zero documentos do tenant.
