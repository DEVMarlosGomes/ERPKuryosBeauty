# Expedições comerciais legadas - checkpoint HML

Data: 2026-09-25  
Status: **APLICADO E VERIFICADO SOMENTE EM HOMOLOGAÇÃO**

## Resultado

- 338 expedições comerciais preservadas em `legacy_expedition_reviews`.
- 325 registros do tipo expedido, 8 devoluções, 2 retrabalhos e 3 furtos legados.
- 173 registros classificados como histórico conciliado.
- 165 registros encaminhados para revisão manual.
- 1.336 referências de SKU resolvidas diretamente, 1 por alias e 85 não resolvidas.

Todos os registros permanecem com `historical_only = true`, `operational_eligible = false`, `stock_replay_allowed = false`, `activation_status = bloqueado` e `review_status = pendente_revisao`.

## Isolamento operacional confirmado

As contagens permaneceram iguais antes e depois da onda:

- `expedicao_ordens`: 0;
- `expedicao_transacoes`: 0;
- `orders`: 16;
- `ops`: 1;
- `estoque_saldos_lote`: 0;
- `inventory_ledger`: 0;
- `wms_paletes`: 0;
- `faturamento_notas`: 0;
- `faturamento_duplicatas`: 0;
- `devolucoes_cliente`: 0;
- `retrabalho_ordens`: 0.

As 112 coleções anteriores mantiveram contagem, hash canônico dos documentos e fingerprint dos índices sem divergências. Os 338 documentos e payloads de origem passaram na verificação de hash sem falhas.

## Snapshot e retorno

- Snapshot: `C:\Users\MARLOS\.kuryos\backups\kuryos-erp-hml-pre-expedition-history-20260925.archive.gz`
- SHA-256: `b3781d9ab004d8516845022a0dbaf63d3f112dd57b9b4196f8767bf9f3fe636a`
- Conteúdo: 112 coleções e 13.605 documentos.
- Restauração integral: verificada; banco descartável removido.
- Rollback seletivo: verificado em banco local descartável; os 338 documentos foram removidos e o banco foi apagado.

## Limites desta onda

Nenhuma expedição operacional, baixa de PA, alteração de pedido, carga, nota fiscal, devolução, retrabalho ou movimento de estoque foi criado. A promoção de qualquer histórico exige resolução humana dos vínculos e uma onda separada. Produção não foi acessada nem alterada.
