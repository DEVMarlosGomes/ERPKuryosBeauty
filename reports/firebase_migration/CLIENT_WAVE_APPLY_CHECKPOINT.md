# FIREBASE CURRENT - CLIENT WAVE HOMOLOGATION CHECKPOINT

Data: 2026-09-24  
Plano: `e5669507-b321-5187-96fa-7246cc909085`  
Status: **APLICADO E VERIFICADO SOMENTE EM HOMOLOGACAO**

## Escopo aplicado

- 56 clientes novos importados para `crm_clients`.
- Todos os 56 clientes novos foram posicionados em `prospeccao`.
- 56 tarefas comerciais iniciais criadas em `workflow_tasks`.
- 56 eventos de auditoria criados em `audit_logs`.
- Nenhum cliente que ja existia foi atualizado ou reposicionado.
- Nenhuma escrita foi realizada nas colecoes de P&D.
- A origem Firebase analisada nao possui nos de amostras/P&D; por isso nao havia amostra nova elegivel para inserir como `solicitada` nesta onda.

## Contagens do tenant

| Colecao | Antes | Depois | Resultado |
| --- | ---: | ---: | --- |
| `crm_clients` | 15 | 71 | +56 |
| `workflow_tasks` | 361 | 417 | +56 |
| `audit_logs` | 3320 | 3376 | +56 |
| `crm_samples` | 30 | 30 | inalterado |
| `pd_requests` | 95 | 95 | inalterado |
| `pd_developments` | 95 | 95 | inalterado |

## Prova de preservacao

- Os 15 clientes anteriores possuem a mesma contagem e o mesmo hash canonico do snapshot.
- `crm_samples`, `pd_requests` e `pd_developments` possuem as mesmas contagens, hashes de documentos e fingerprints de indices do snapshot.
- As tres colecoes de P&D possuem zero documentos marcados por este plano.
- Os 56 clientes novos possuem IDs e codigos CLI4 unicos e estao todos em `prospeccao`.
- Relatorio tecnico: `CLIENT_WAVE_VERIFICATION.json`.

## Snapshot retido para retorno

- Arquivo: `C:\Users\MARLOS\.kuryos\backups\kuryos-erp-hml-preapply-e5669507-20260924.archive.gz`
- SHA-256: `da4a0eaa366716c6ba06d5b11b5c378f15a194e41f9f70991f722155d4d1d7b1`
- O restore completo foi ensaiado em banco local descartavel e reproduziu 101 colecoes e 9.041 documentos sem divergencias de conteudo ou indices.
- O snapshot deve ser mantido ate a homologacao visual ser aprovada.

## Retorno seletivo desta onda

O rollback seletivo remove somente os documentos marcados com o ID deste plano. Ele nao deve ser executado enquanto a validacao visual estiver em andamento.

```powershell
python scripts/apply_firebase_clients_hml.py rollback `
  --env firebase-migration-hml.env `
  --source "C:\Users\MARLOS\Downloads\prod-kuryos-default-rtdb-export.json" `
  --client-map reports/firebase_migration/CLIENT_ID_MAP.json `
  --snapshot "C:\Users\MARLOS\.kuryos\backups\kuryos-erp-hml-preapply-e5669507-20260924.archive.gz" `
  --snapshot-sha256 da4a0eaa366716c6ba06d5b11b5c378f15a194e41f9f70991f722155d4d1d7b1 `
  --report reports/firebase_migration/CLIENT_WAVE_ROLLBACK_RESULT.json
```

## Runtime local

- Backend local: `http://localhost:8000`, apontando exclusivamente para `kuryos_erp_homologacao`.
- Frontend local: `http://localhost:3000`.
- A API autenticada confirmou o tenant esperado, 71 clientes totais e 56 clientes desta onda.
- O lancador `scripts/start_homologation_local.py` recusa o host de producao e o nome de banco diferente da homologacao aprovada.

## Producao

- Nenhuma escrita foi feita no MongoDB de producao.
- O usuario de producao validado permanece somente leitura em `kuryos`.
