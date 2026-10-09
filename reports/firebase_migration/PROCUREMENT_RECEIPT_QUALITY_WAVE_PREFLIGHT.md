# Compras, recebimentos e CQ - preflight HML

Gerado em: 2026-09-25T13:10:25.049826+00:00

Modo: somente leitura. Nenhuma escrita no Mongo.

## Contagens

- `purchase_request`: 4
- `purchase_order`: 16
- `receipt`: 7
- `finished_goods_check`: 7
- `nonconformity`: 2

## Regra

Os documentos podem seguir apenas para filas isoladas de revisão. Recebimentos e conferências de PA não podem reproduzir saldo, lote, palete, RA ou ledger.
