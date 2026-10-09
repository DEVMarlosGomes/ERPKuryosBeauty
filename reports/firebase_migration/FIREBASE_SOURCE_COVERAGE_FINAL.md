# Cobertura final Firebase → ERP HML

Data: 2026-09-25  
Fonte: `prod-kuryos-default-rtdb-export.json`  
SHA-256: `7b6ba88ff260d4b8c18e4a057e9e6732d77d394c88d4b4bd034e08a7fe0b83e4`

## Conclusão

Os **45 nós** existentes na exportação foram classificados e possuem destino controlado na homologação. Não restou nó da fonte atual sem tratamento.

## Destinos por onda

- Clientes: `clientes`.
- Fornecedores, materiais e SKUs: `fornecedores`, `materiais`, `produtos`, `sku_historico`.
- Fórmulas e BOM: `formulas`, `bom`.
- Pedidos e OPs: `pedidos_comerciais`, `pedidos`, `ops`.
- Estoque de corte: `enderecos_estoque`, `estoque_lotes`.
- Compras, recebimento e qualidade: `solicitacoes_compra`, `pedidos_compra`, `recebimentos_operacoes`, `conferencias_pa`, `lotes_internos`, `nao_conformidades`.
- Expedição: `expedicoes_comerciais`.
- RH: `rh_cargos`, `usuarios`.
- Históricos complementares: `especificacoes`, `programacao`, `paradas_historico`, `intervalosApontados`, `turnosEncerrados`, `perdas`, `precos_venda`, `processos_cotacao`.
- Arquivo final isolado: `ajustes_planejamento`, `comercial_eventos`, `config`, `contadores_lote_interno`, `email_notifications_state`, `emails_diretoria`, `estado_linhas`, `estoque`, `estrutura_ruas`, `historico_materiais`, `insumos`, `movimentos_estoque`, `notificacoes_comercial`, `notificacoes_op_encerrada`, `parametros_pa`, `registros`.

## Limite da conclusão

Esta cobertura corresponde exatamente ao arquivo exportado cujo hash aparece acima. Dados criados ou alterados posteriormente no Firebase remoto exigem nova exportação e uma comparação incremental; não devem ser inferidos nem copiados por replay cego.

Os registros bloqueados ou em revisão foram preservados para decisão humana, mas não foram promovidos a operação. Isso inclui saldos agregados, movimentos ambíguos, dados mestres incompletos, estados de notificação e usuários legados sem vínculo seguro com a autenticação do ERP.
