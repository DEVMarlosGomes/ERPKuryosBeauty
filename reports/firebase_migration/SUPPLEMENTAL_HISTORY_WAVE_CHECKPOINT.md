# Históricos complementares - checkpoint HML

Data: 2026-09-25  
Status: **APLICADO E VERIFICADO SOMENTE EM HOMOLOGAÇÃO**

## Resultado

Foram preservados 597 documentos em `legacy_supplemental_history_reviews`:

- 213 especificações;
- 51 programações legadas;
- 141 paradas de produção;
- 13 intervalos apontados;
- 34 turnos encerrados;
- 22 grupos de perdas;
- 110 preços de venda;
- 13 processos de cotação.

Todos permanecem com `historical_only = true`, `operational_eligible = false`, `operational_replay_allowed = false`, `activation_status = bloqueado` e `review_status = pendente_revisao`.

## Reconciliação

- 194 especificações conciliadas e 19 em revisão manual.
- 49 programações conciliadas e 2 em revisão manual.
- 141 paradas, 13 intervalos, 34 turnos, 22 perdas e 110 preços preservados como histórico conciliado.
- 3 processos de cotação conciliados e 10 em revisão manual.

## Isolamento operacional

As seguintes contagens permaneceram inalteradas:

- `skus`: 382;
- `pcp_programacao`: 0;
- `production_order_events`: 0;
- `estoque_movimentos`: 0;
- `inventory_ledger`: 0;
- `compras_demandas`: 0;
- `compras_pos`: 0.

As 115 coleções anteriores mantiveram contagem, hash canônico e índices sem divergências. Os 597 documentos e payloads passaram na verificação de hash sem falhas.

## Snapshot e retorno

- Snapshot: `C:\Users\MARLOS\.kuryos\backups\kuryos-erp-hml-pre-supplemental-history-20260925.archive.gz`
- SHA-256: `5c515806be01f3097cfb48df095d346e1daa73eb28d181d15885e9486085cefc`
- Conteúdo: 115 coleções e 13.974 documentos.
- Restauração integral: verificada.
- Rollback seletivo: verificado em banco local descartável; 597 documentos removidos e banco apagado.

Nenhum preço vigente, programação, perda, saldo, evento de produção ou cotação operacional foi criado. Produção não foi acessada nem alterada.
