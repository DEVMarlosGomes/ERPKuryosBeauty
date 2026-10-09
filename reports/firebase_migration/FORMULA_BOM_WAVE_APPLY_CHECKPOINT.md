# Formula/BOM legacy review wave — HML checkpoint

## Outcome

Status: **APPLIED_HOMOLOGATION_VERIFIED**.

The user-approved Option A was applied only to `kuryos_erp_homologacao`. Firebase formulas and BOMs were retained in the isolated `legacy_formula_bom_reviews` collection as blocked review records. No record was activated for MRP or production.

## Applied scope

- Formula review records: **197**.
- Packaging BOM review records: **246**.
- Total review records: **443**.
- `operational_eligible=true`: **0**.
- Records with activation status other than `bloqueado`: **0**.
- Document hash failures: **0**.
- Original payload hash failures: **0**.

Each review record retains its Firebase source key and payload, source status/version, resolved SKU and material references when available, classification, blocking reasons and migration provenance.

## Operational isolation

The following tenant counts were identical before and after this wave:

- `produtos_pai`: **0**.
- `bom_items`: **0**.
- SKUs linked to a product parent: **0**.

The prior **104 collections** matched the verified pre-wave snapshot in document count, canonical document hash and index hash.

## Snapshot and recovery

- Archive: `C:\Users\MARLOS\.kuryos\backups\kuryos-erp-hml-pre-formula-bom-review-e5669507-20260924.archive.gz`
- SHA-256: `5fddb5a16c0cf127499a88dbb025168feacbd68315bc0e4a934d9666ba655785`
- Snapshot contents: **104 collections / 10,879 documents**.
- Restore drill: **verified**, then the disposable local restore was removed.
- Selective rollback drill: **verified on a disposable local database**, removing all 443 review documents and the migration-created collection/indexes.

Selective HML rollback, if explicitly requested:

```powershell
python scripts/apply_firebase_formula_bom_review_hml.py rollback `
  --env firebase-migration-hml.env `
  --source "C:\Users\MARLOS\Downloads\prod-kuryos-default-rtdb-export.json" `
  --preflight reports/firebase_migration/FORMULA_BOM_WAVE_PREFLIGHT.json `
  --snapshot "C:\Users\MARLOS\.kuryos\backups\kuryos-erp-hml-pre-formula-bom-review-e5669507-20260924.archive.gz" `
  --snapshot-sha256 5fddb5a16c0cf127499a88dbb025168feacbd68315bc0e4a934d9666ba655785 `
  --apply-report reports/firebase_migration/FORMULA_BOM_WAVE_APPLY.json `
  --report reports/firebase_migration/FORMULA_BOM_WAVE_ROLLBACK.json
```

The rollback refuses to proceed if the collection count, ownership markers or any migrated document hash has changed.

## Required next gate

These records intentionally do not appear as active product structures. Before promotion, P&D/Cadastro must resolve pending materials, select the valid version, approve the formula and packaging BOM, and decide product-parent grouping. Promotion requires a separate, explicitly approved wave.

