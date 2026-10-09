# Orders and OP wave — preflight

Generated at `2026-09-25T02:09:58.815299+00:00`.

## Safety boundary

- Mode: **read-only reconciliation against HML**.
- Production writes: **no**.
- Homologation writes: **no**.
- Verified HML snapshot baseline: **16 orders**, **1 OPs**, **71 clients**.
- Decision gate: **paused before apply**.

## Commercial orders

- Source commercial orders: **76**.

| Classification | Count |
|---|---:|
| `archive_ready` | 74 |
| `manual_review` | 2 |

| Item SKU resolution | Count |
|---|---:|
| `direct` | 428 |
| `unresolved` | 3 |
| `alias` | 1 |

## Production order lines

- Source order lines: **377**.

| Classification | Count |
|---|---:|
| `archive_ready` | 345 |
| `manual_review` | 32 |

| Legacy status | Count |
|---|---:|
| `Concluído` | 273 |
| `Produção Parcial` | 55 |
| `Não Iniciado` | 37 |
| `Programado` | 11 |
| `Em Produção` | 1 |

## Production orders (OPs)

- Source OPs: **1388**.
- Non-terminal OPs requiring an explicit business decision: **58**.

| Classification | Count |
|---|---:|
| `historical_archive_ready` | 1014 |
| `manual_review` | 316 |
| `open_requires_decision` | 58 |

| Legacy status | Count |
|---|---:|
| `Concluído` | 1293 |
| `Cancelado` | 37 |
| `Não Iniciado` | 26 |
| `Programado` | 16 |
| `Produção Parcial` | 8 |
| `Aguardando Confirmação` | 6 |
| `Em Produção` | 2 |

## Recommended controlled policy

1. Import terminal orders/OPs only as immutable legacy history, with no inventory, reservation, ledger or accounting side effects.
2. Keep non-terminal OPs in a review queue; do not schedule or consume stock automatically.
3. Preserve the commercial-order → order-line → OP relationship when uniquely resolved.
4. Do not fabricate CGI, approval, BOM, lot balance, PA pallet or shipment events.
5. Promote an open legacy demand only through a separate reviewed action that validates current SKU/BOM and available stock.

Detailed per-record reconciliation is in `reports/firebase_migration/ORDER_OP_WAVE_PREFLIGHT.json`.
