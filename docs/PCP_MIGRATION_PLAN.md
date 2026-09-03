# PCP Migration Plan - FASE 0

## Principio

A migracao do PCP-Kuryos para o ERP deve ser dry-run first. Nenhum dado legado deve ser importado diretamente sem normalizacao, validacao de tenant, deduplicacao e relatorio de inconsistencias.

## Fases

| Fase | Objetivo | Saida |
| --- | --- | --- |
| 0 | Inventario e matriz | Documentos desta pasta e `reports/pcp_audit`. |
| 1 | Extracao legado | Snapshot JSON/CSV das entidades PCP. |
| 2 | Normalizacao | Mapear IDs, status, datas, linhas, pedidos, produtos, formulas e materiais. |
| 3 | Validacao | Relatorio de duplicados, orfaos, saldos negativos, OP sem pedido e pedido sem SKU. |
| 4 | Dry-run import | Simular insercao/update no modelo ERP sem gravar. |
| 5 | Apply controlado | Importar somente com flag explicita e backup/snapshot. |
| 6 | Conciliacao | Comparar contagens, saldos, OPs, pedidos, historicos e KPIs. |

## Scripts previstos

| Script | Funcao |
| --- | --- |
| `scripts/pcp_migration/extract_legacy.py` | Extrair dados do legado para arquivos locais versionados por data. |
| `scripts/pcp_migration/transform_legacy.py` | Transformar para contratos ERP. |
| `scripts/pcp_migration/validate_legacy.py` | Validar duplicidades, orfaos e regras de dominio. |
| `scripts/pcp_migration/import_dry_run.py` | Simular importacao e gerar diff/relatorio. |
| `scripts/pcp_migration/import_apply.py` | Aplicar importacao somente com `--apply` e ambiente confirmado. |

## Validacoes obrigatorias

- Todo registro importado tem `tenant_id`.
- Nenhum pedido e criado duplicado pelo mesmo `source_id`.
- OP sem pedido exige tipo excecao e motivo.
- OP vinculada nao pode exceder saldo do item.
- SKU duplicado bloqueia importacao ate decisao.
- Formula/BOM sem produto aprovado vira pendencia, nao OP liberada.
- Material recebido sem qualidade liberada nao entra como disponivel.

