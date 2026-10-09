# RH legado - checkpoint HML

Data: 2026-09-25  
Status: **APLICADO E VERIFICADO SOMENTE EM HOMOLOGAÇÃO**

## Resultado

- 3 cargos históricos e 13 usuários legados preservados em `legacy_hr_reviews`.
- 3 usuários reconciliados por e-mail com contas já existentes.
- 10 usuários sem conta correspondente encaminhados para revisão manual.
- Nenhuma conta, colaborador, cargo operacional, senha, sessão, papel ou permissão foi criado ou alterado.

Todos os registros permanecem com `historical_only = true`, `operational_eligible = false`, `account_creation_allowed = false`, `permission_replay_allowed = false`, `activation_status = bloqueado` e `review_status = pendente_revisao`.

## Segurança e isolamento

- Campos de senha e tokens são removidos do payload antes da persistência.
- A verificação encontrou zero campos sensíveis proibidos.
- `users`: permaneceu com 14 documentos do tenant.
- `rh_cargos`, `rh_colaboradores`, `rh_avaliacoes` e `rh_ferias`: permaneceram com zero documentos do tenant.
- As 113 coleções anteriores mantiveram contagem, hash canônico e índices sem divergências.
- Os 16 documentos e payloads sanitizados passaram na verificação de hash.

## Snapshot e retorno

- Snapshot: `C:\Users\MARLOS\.kuryos\backups\kuryos-erp-hml-pre-hr-legacy-20260925.archive.gz`
- SHA-256: `49848d4f9202de364ed0d4bf0905bd128e939f4ee9433e57060c2dbf4617210f`
- Conteúdo: 113 coleções e 13.943 documentos.
- Restauração integral: verificada; banco descartável removido.
- Rollback seletivo: verificado; os 16 registros foram removidos no ensaio e o banco local descartável foi apagado.

Produção não foi acessada nem alterada.
