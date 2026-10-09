# FIREBASE CURRENT - MATERIAL WAVE HOMOLOGATION CHECKPOINT

Data: 2026-09-24  
Plano: `e5669507-b321-5187-96fa-7246cc909085`  
Status: **APLICADO E VERIFICADO SOMENTE EM HOMOLOGACAO**

## Resultado

- 647 materiais comprados criados em `materiais`.
- 199 fragrancias criadas em `fragrancias`.
- 4 contadores criados para evitar colisao dos proximos codigos MP, EP, ES e FR.
- 93 materiais ambiguos ou com unidade atipica permaneceram bloqueados.
- Nenhum vinculo operacional de fornecedor foi inferido; 570 referencias legadas foram preservadas apenas em `_legacy_supplier_refs`.
- Nenhum material, fragrancia ou contador anterior foi sobrescrito.

## Regra aplicada

- EP com unidade `un` foi cadastrado como material EP.
- ES com unidade `un` foi cadastrado como material ES.
- MPGR com unidade `kg` ou `L` foi cadastrado como material MP.
- MPES com unidade `kg` foi cadastrado como fragrancia.
- Unidade de compra vazia recebeu a unidade de estoque.
- ET, MU e unidades atipicas ficaram fora da onda.

## Validacao

- 846 documentos de cadastro correspondem exatamente aos hashes do manifesto.
- Codigos de materiais e fragrancias sao unicos.
- Zero vinculos operacionais de fornecedor foram criados automaticamente.
- As outras 101 colecoes permaneceram identicas ao snapshot.
- Mapa aplicado: `MATERIAL_ID_MAP_APPLIED.json`.
- Relatorio: `MATERIAL_WAVE_VERIFICATION.json`.

## Snapshot retido

- Arquivo: `C:\Users\MARLOS\.kuryos\backups\kuryos-erp-hml-pre-materials-e5669507-20260924.archive.gz`
- SHA-256: `2c317dc41c86e5569eb7fa74efb54f8aa00ccf697ade3b85afd2a74428c7a453`
- Tamanho: 829.922 bytes.
- Conteudo: 104 colecoes e 9.634 documentos, incluindo clientes e fornecedores aprovados.
- Restore integral testado com zero falhas.

## Rollback seletivo

O rollback se recusa a remover qualquer documento editado depois da migracao.

```powershell
python scripts/apply_firebase_materials_hml.py rollback `
  --env firebase-migration-hml.env `
  --source "C:\Users\MARLOS\Downloads\prod-kuryos-default-rtdb-export.json" `
  --material-map reports/firebase_migration/MATERIAL_ID_MAP.json `
  --snapshot "C:\Users\MARLOS\.kuryos\backups\kuryos-erp-hml-pre-materials-e5669507-20260924.archive.gz" `
  --snapshot-sha256 2c317dc41c86e5569eb7fa74efb54f8aa00ccf697ade3b85afd2a74428c7a453 `
  --apply-report reports/firebase_migration/MATERIAL_WAVE_APPLY_RESULT.json `
  --report reports/firebase_migration/MATERIAL_WAVE_ROLLBACK_RESULT.json
```

## Producao

- Nenhuma escrita foi realizada no MongoDB de producao.
