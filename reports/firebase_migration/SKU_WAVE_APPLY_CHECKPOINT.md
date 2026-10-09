# FIREBASE CURRENT - LEGACY SKU WAVE HOMOLOGATION CHECKPOINT

Data: 2026-09-24  
Plano: `e5669507-b321-5187-96fa-7246cc909085`  
Politica: **A - LEGADO AUTORIZADO**  
Status: **APLICADO E VERIFICADO SOMENTE EM HOMOLOGACAO**

## Resultado

- 382 SKUs historicos inseridos com seus codigos originais.
- Todos os 382 possuem cliente reconciliado.
- 328 preservaram status ativo e 54 preservaram status inativo.
- Todos foram marcados com `origem_contratual_status = legado_autorizado` e `legado_sem_cgi = true`.
- Nenhum CGI ficticio foi criado.
- Nenhum codigo novo `CAT3-CLI4-SEQ4` foi gerado para substituir o historico.
- 7 aliases historicos foram vinculados aos respectivos SKUs de destino.
- 13 contadores foram protegidos contra colisao com codigos historicos que ja seguem o formato atual.
- 3 registros sem cliente permaneceram bloqueados.

## Validacao

- Codigos unicos: aprovado.
- Vínculos de cliente: aprovado.
- Hash dos 382 SKUs e 13 contadores: aprovado, sem divergencias.
- Outras 102 colecoes: inalteradas em relacao ao snapshot.
- Mapa aplicado: `SKU_ID_MAP_APPLIED.json`.
- Relatorio: `SKU_WAVE_VERIFICATION.json`.

## Snapshot retido

- Arquivo: `C:\Users\MARLOS\.kuryos\backups\kuryos-erp-hml-pre-skus-e5669507-20260924.archive.gz`
- SHA-256: `3bf7a25b644c1ca6ae174ecd20b76a9c0a67479a161cc4c5ee8861a34d098ee1`
- Tamanho: 918.607 bytes.
- Conteudo: 104 colecoes e 10.484 documentos.
- Restore integral testado com zero falhas.

## Rollback seletivo

O rollback se recusa a remover SKU ou contador editado depois da migracao.

```powershell
python scripts/apply_firebase_legacy_skus_hml.py rollback `
  --env firebase-migration-hml.env `
  --source "C:\Users\MARLOS\Downloads\prod-kuryos-default-rtdb-export.json" `
  --client-map reports/firebase_migration/CLIENT_ID_MAP.json `
  --client-apply reports/firebase_migration/CLIENT_WAVE_APPLY_RESULT.json `
  --snapshot "C:\Users\MARLOS\.kuryos\backups\kuryos-erp-hml-pre-skus-e5669507-20260924.archive.gz" `
  --snapshot-sha256 3bf7a25b644c1ca6ae174ecd20b76a9c0a67479a161cc4c5ee8861a34d098ee1 `
  --apply-report reports/firebase_migration/SKU_WAVE_APPLY_RESULT.json `
  --report reports/firebase_migration/SKU_WAVE_ROLLBACK_RESULT.json
```

## Producao

- Nenhuma escrita foi realizada no MongoDB de producao.
