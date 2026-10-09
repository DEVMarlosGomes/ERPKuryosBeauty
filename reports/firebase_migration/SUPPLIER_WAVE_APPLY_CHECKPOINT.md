# FIREBASE CURRENT - SUPPLIER WAVE HOMOLOGATION CHECKPOINT

Data: 2026-09-24  
Plano: `e5669507-b321-5187-96fa-7246cc909085`  
Status: **APLICADO E VERIFICADO SOMENTE EM HOMOLOGACAO**

## Resultado

- 383 fornecedores inseridos em `compras_fornecedores`.
- 383 CNPJs unicos e validados.
- 383 codigos internos deterministas no formato `FOR-FB-NNNN`.
- Todos iniciaram com `homologacao.status = nao_iniciada`.
- Contatos, endereco, categorias, site, condicao de pagamento, certificacoes e referencia WebMais foram preservados quando disponiveis.
- 20 fornecedores permaneceram bloqueados: 6 registros em conflito e 14 sem CNPJ valido.
- Nenhuma tentativa foi feita de corrigir ou inserir automaticamente os 20 bloqueados.

## Prova de isolamento

- Os 383 documentos gravados correspondem exatamente aos hashes previstos no manifesto de aplicacao.
- Nenhum documento marcado apresenta divergencia posterior a carga.
- As outras 103 colecoes mantiveram contagem, hash de documentos e fingerprint de indices identicos ao snapshot anterior a esta onda.
- Relatorio: `SUPPLIER_WAVE_VERIFICATION.json`.

## Snapshot retido

- Arquivo: `C:\Users\MARLOS\.kuryos\backups\kuryos-erp-hml-pre-suppliers-e5669507-20260924.archive.gz`
- SHA-256: `6942224d2871eb2f22b673901a9c357aa6e33267bc11862a611012a461bdee10`
- Tamanho: 750.546 bytes.
- Conteudo: 104 colecoes e 9.248 documentos, incluindo a onda de clientes ja homologada.
- O restore integral foi testado e a base descartavel foi removida apos a equivalencia exata.

## Rollback seletivo

O rollback verifica o hash atual de cada fornecedor e se recusa a apagar registros que tenham sido editados depois da carga.

```powershell
python scripts/apply_firebase_suppliers_hml.py rollback `
  --env firebase-migration-hml.env `
  --source "C:\Users\MARLOS\Downloads\prod-kuryos-default-rtdb-export.json" `
  --supplier-map reports/firebase_migration/SUPPLIER_ID_MAP.json `
  --snapshot "C:\Users\MARLOS\.kuryos\backups\kuryos-erp-hml-pre-suppliers-e5669507-20260924.archive.gz" `
  --snapshot-sha256 6942224d2871eb2f22b673901a9c357aa6e33267bc11862a611012a461bdee10 `
  --apply-report reports/firebase_migration/SUPPLIER_WAVE_APPLY_RESULT.json `
  --report reports/firebase_migration/SUPPLIER_WAVE_ROLLBACK_RESULT.json
```

## Ondas ainda bloqueadas

- 20 fornecedores exigem decisao humana sobre conflito/CNPJ.
- 939 materiais exigem classificacao humana de dominio MP, EP, ES, RT ou fragrancia.
- 392 SKUs historicos exigem resolucao por alias; gerar SKU automaticamente continua proibido.
- 197 formulas e 246 BOMs dependem da resolucao dos materiais/SKUs.
- 453 pedidos dependem de cliente, SKU, CGI e demais vinculos resolvidos.
- 1.388 OPs permanecem em revisao manual; apontamentos historicos nao serao reproduzidos.
- 39 lotes e o estoque dependem de corte fisico, CQ e WMS.

## Producao

- Nenhuma escrita foi realizada no MongoDB de producao.
