# Compras, recebimentos e CQ - checkpoint HML

Data: 2026-09-25  
Status: **APLICADO E VERIFICADO SOMENTE EM HOMOLOGAÇÃO**

## Resultado

- 4 solicitações e 16 pedidos de compra em `legacy_procurement_reviews`.
- 7 operações de recebimento em `legacy_receipt_reviews`.
- 7 conferências de PA e 2 não conformidades em `legacy_quality_reviews`.
- Total: 36 documentos históricos preservados com payload de origem.
- Todos permanecem com `historical_only = true`, `operational_eligible = false`, `activation_status = bloqueado` e `review_status = pendente_revisao`.

## Reconciliação

- Solicitações de compra: 2 conciliadas para arquivo e 2 em revisão manual.
- Pedidos de compra: 11 conciliados para arquivo e 5 em revisão manual.
- Recebimentos: 7 em revisão histórica; reprodução de estoque proibida.
- Conferências de PA: 7 em revisão histórica; reprodução de PA/palete proibida.
- Não conformidades: 2 conciliadas para arquivo.

## Isolamento operacional confirmado

As contagens permaneceram iguais antes e depois da onda:

- `compras_demandas`: 0;
- `compras_pos`: 0;
- `recebimentos`: 0;
- `estoque_saldos_lote`: 0;
- `inventory_ledger`: 0;
- `wms_paletes`: 0;
- `cq_rncs`: 0;
- `conferencias_pa`: 0.

As 109 coleções anteriores ao apply mantiveram contagem, hash canônico dos documentos e fingerprint dos índices sem divergências. Os 36 documentos da onda e seus payloads de origem passaram na verificação de hash sem falhas.

## Snapshot e retorno

- Snapshot: `C:\Users\MARLOS\.kuryos\backups\kuryos-erp-hml-pre-procurement-receipt-quality-20260925.archive.gz`
- SHA-256: `105347da73aa02e2850c256ed25be288ccf52651a7c5e6e14cb2d2ea7d749ab1`
- Conteúdo: 109 coleções e 13.569 documentos.
- Restauração integral: verificada; banco descartável removido.
- Rollback seletivo: verificado em banco local descartável; 20 + 7 + 9 documentos removidos e banco descartável apagado.

## Limites desta onda

Nenhum pedido de compra operacional, recebimento, saldo, lote, palete, RA, movimento de ledger, conferência de PA operacional ou RNC foi criado. A promoção futura exige reconciliação humana e uma onda separada. Produção não foi acessada nem alterada.
