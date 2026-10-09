# Promoção dos cargos de RH - checkpoint HML

Data: 2026-09-25  
Status: **APLICADO E VERIFICADO SOMENTE EM HOMOLOGAÇÃO**

## Estrutura remota verificada

O remoto separa contas de acesso (`usuarios`) dos dados organizacionais (`rh_cargos`, `rh_colaboradores`, avaliações e férias). A leitura anônima do Firebase retorna 401; portanto, a promoção utilizou exclusivamente o export Firebase validado pelo SHA-256 da migração.

## Resultado operacional

Foram criados exatamente três documentos em `rh_cargos`:

1. `AUXILIAR DE PRODUCAO I` - setor `PRODUCAO`, nível `1`, ativo.
2. `AUXILIAR DE PRODUCAO II` - setor `PRODUCAO`, nível `2`, ativo.
3. `AUXILIAR DE PRODUCAO III` - setor `PRODUCAO`, nível `3`, ativo.

Os três registros correspondentes em `legacy_hr_reviews` foram marcados como promovidos e vinculados aos IDs operacionais determinísticos.

## Proteções

- `users`: permaneceu com 14 contas do tenant.
- `rh_colaboradores`: permaneceu com 0.
- `rh_avaliacoes`: permaneceu com 0.
- `rh_ferias`: permaneceu com 0.
- Nenhuma senha, papel, permissão ou módulo foi alterado.
- Os 10 usuários legados sem correspondência continuam em revisão; não foram convertidos indevidamente em colaboradores.
- 112 coleções não envolvidas mantiveram contagem, hash canônico e índices sem divergências.

## Snapshot e retorno

- Snapshot: `C:\Users\MARLOS\.kuryos\backups\kuryos-erp-hml-pre-hr-cargo-promotion-20260925.archive.gz`
- SHA-256: `e31df64895be4cc0d8082b82c115fc71bc8a03f5e7d260b2f2aa93936c012393`
- Conteúdo: 114 coleções e 13.971 documentos.
- Restauração integral: verificada.
- Rollback seletivo: verificado em banco local descartável; três cargos removidos e três revisões restauradas exatamente.

Produção não foi alterada.
