# Arquivo final da fonte Firebase — checkpoint HML

Data: 2026-09-25  
Status: **APLICADO E VERIFICADO SOMENTE EM HOMOLOGAÇÃO**

## Resultado

- 1.558 unidades restantes da exportação foram preservadas em `legacy_source_archive_reviews`.
- 1.307 documentos foram classificados como referência histórica.
- 251 documentos foram classificados como `excluded_no_replay`.
- Todos possuem `operational_eligible = false`, `operational_replay_allowed = false` e `activation_status = bloqueado`.
- Nenhum saldo, movimento, contador, configuração ou notificação legado foi reativado.

## Nós preservados

- `ajustes_planejamento`: 2
- `comercial_eventos`: 1
- `config`: 32
- `contadores_lote_interno`: 1
- `email_notifications_state`: 2
- `emails_diretoria`: 2
- `estado_linhas`: 3
- `estoque`: 95
- `estrutura_ruas`: 19
- `historico_materiais`: 901
- `insumos`: 1
- `movimentos_estoque`: 72
- `notificacoes_comercial`: 8
- `notificacoes_op_encerrada`: 41
- `parametros_pa`: 2
- `registros`: 376

## Proteção e verificação

- Snapshot anterior: `C:\Users\MARLOS\.kuryos\backups\kuryos-erp-hml-pre-final-source-archive-20260925.archive.gz`
- SHA-256: `6965368591c342b2702482d2d4b3e613479e748a6e2767cb6349a27c9ff03a0f`
- Snapshot restaurado com sucesso: 116 coleções e 14.571 documentos.
- As 116 coleções anteriores conservaram documentos e índices sem divergência.
- 1.558 hashes de documentos e payloads foram validados.
- As contagens de CRM, P&D, SKUs, materiais, pedidos, PCP, estoque, compras, usuários e RH permaneceram iguais.
- Rollback seletivo ensaiado em banco local descartável: 1.558 documentos removidos e banco de ensaio apagado.
- Produção não foi acessada nem alterada.

## Regra de segurança

Esta coleção é um arquivo de consulta e saneamento. Seus documentos não podem alimentar automaticamente saldo, ledger, MRP, PCP, notificações, contadores ou configuração do ERP. Qualquer promoção futura exige uma onda específica, reconciliação e aprovação humana.
