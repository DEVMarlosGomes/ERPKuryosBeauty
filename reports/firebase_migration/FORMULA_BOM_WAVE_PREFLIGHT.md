# Formula/BOM wave — preflight

Generated at `2026-09-24T22:41:37.619163+00:00`.

## Safety boundary

- Mode: **read-only local reconciliation**.
- MongoDB connections opened: **no**.
- Production writes: **no**.
- HML writes: **no**.
- Applied maps used: 846 materials and 382 SKUs.
- Decision gate: **paused before apply**.

## Formulas (bulk)

- Source records: **197**.
- Resolved target SKUs: **186**.
- Target SKUs with more than one formula/version: **9**.

| Record classification | Count |
|---|---:|
| `partial_pending` | 106 |
| `safe_full` | 87 |
| `empty` | 2 |
| `unresolved_sku` | 2 |

| Formula item state | Count |
|---|---:|
| `mapped` | 976 |
| `blank_pending` | 239 |
| `blocked_material` | 40 |
| `blank` | 13 |
| `nonpositive_quantity` | 1 |

## BOMs (packaging)

- Source records: **246**.
- Resolved target SKUs: **219**.
- Target SKUs with more than one BOM/version: **25**.

| Record classification | Count |
|---|---:|
| `partial_pending` | 231 |
| `safe_full` | 8 |
| `empty` | 5 |
| `unresolved_sku` | 2 |

| BOM item state | Count |
|---|---:|
| `mapped` | 752 |
| `blocked_material` | 288 |
| `blank_pending` | 164 |
| `nonpositive_quantity` | 50 |
| `blank` | 15 |

## Pairing by resolved target SKU

| Situation | Count |
|---|---:|
| `no_fully_safe_pair` | 137 |
| `safe_formula_only` | 84 |
| `safe_bom_only` | 7 |
| `safe_formula_and_bom` | 1 |

## Approved operational readiness

| Check | Count |
|---|---:|
| `approved_safe_formula_records` | 5 |
| `approved_safe_formula_target_skus` | 4 |
| `approved_safe_bom_records` | 0 |
| `approved_safe_bom_target_skus` | 0 |
| `approved_complete_target_skus` | 0 |

There are **0** target SKUs with both an approved, fully resolved formula and an approved, fully resolved packaging BOM. Therefore no complete legacy structure is eligible for automatic operational activation under an approval-preserving policy.

## Blocking decisions before HML apply

1. Define product-parent grouping: one parent per legacy SKU, or consolidate SKUs that truly share the same bulk formula.
2. Define which version becomes active when a target SKU has multiple formula/BOM records.
3. Decide whether rows marked `RASCUNHO` can become operational, or must remain legacy drafts.
4. Keep blank/pending and blocked-material lines outside the operational BOM until their material IDs are resolved.
5. Preserve original Firebase keys, versions, status and payload hashes as migration provenance.

No apply plan should link an SKU to a product-parent or create operational `bom_items` until these rules are approved.

Detailed per-record reconciliation is in `reports/firebase_migration/FORMULA_BOM_WAVE_PREFLIGHT.json`.
