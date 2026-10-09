# Pedidos e OPs — checkpoint da onda de homologação

Data: 2026-09-24

## Estado

Pacote de transformação aplicado e verificado exclusivamente na HML.

- Produção escrita: **não**
- Homologação escrita nesta onda: **sim, apenas nas duas coleções isoladas abaixo**
- Coleções operacionais alteradas: **nenhuma**
- Snapshot pré-onda: **verificado por restauração local**
- Rollback seletivo: **verificado em banco local descartável**

## Conteúdo pronto para aplicação isolada

| Coleção de revisão | Documentos | Regra |
|---|---:|---|
| `legacy_order_reviews` | 453 | 76 pedidos comerciais + 377 linhas |
| `legacy_op_reviews` | 1.388 | OPs históricas/pendentes para revisão |

Todos os 1.841 documentos foram gerados com IDs determinísticos e estão configurados como:

- `operational_eligible: false`
- `activation_status: bloqueado`
- `review_status: pendente_revisao`

Não haverá replay de estoque, lotes, reservas, ledger, apontamentos, PA ou expedição nesta onda.

## Portões executados

1. `ping` autenticado na instância `yxj58uo`: **aprovado**.
2. Dump completo da HML: **aprovado**.
3. Restauração local e comparação de 105 coleções/11.322 documentos: **aprovada**.
4. Dry-run preso ao hash `29cdb3bcbac904140783147a92ed22cdd44fa847421b8842e350b326cae88fe1`: **aprovado**.
5. Aplicação transacional das duas coleções: **aprovada**.
6. Verificação das 105 coleções anteriores: **sem divergências**.
7. Verificação de hashes dos 1.841 documentos novos: **sem divergências**.
8. Rollback seletivo em banco local descartável: **aprovado e banco removido**.

## Garantias verificadas

- `orders`: permaneceu com 16 documentos do tenant.
- `ops`: permaneceu com 1 documento do tenant.
- `estoque_saldos_lote`, `inventory_ledger` e `reservas_lote`: permaneceram com 0.
- Nenhum registro novo possui `operational_eligible: true`.
- Nenhum registro novo deixou o estado `activation_status: bloqueado`.

## Artefatos

- `scripts/reconcile_order_op_wave.py`
- `scripts/apply_firebase_order_op_review_hml.py`
- `scripts/verify_order_op_review_hml.py`
- `scripts/drill_order_op_review_rollback.py`
- `reports/firebase_migration/ORDER_OP_WAVE_PREFLIGHT.json`
- `reports/firebase_migration/ORDER_OP_WAVE_PREFLIGHT.md`
- `reports/firebase_migration/ORDER_OP_WAVE_SNAPSHOT.json`
- `reports/firebase_migration/ORDER_OP_WAVE_DRY_RUN.json`
- `reports/firebase_migration/ORDER_OP_WAVE_APPLY.json`
- `reports/firebase_migration/ORDER_OP_WAVE_VERIFY.json`
- `reports/firebase_migration/ORDER_OP_WAVE_ROLLBACK_DRILL.json`
