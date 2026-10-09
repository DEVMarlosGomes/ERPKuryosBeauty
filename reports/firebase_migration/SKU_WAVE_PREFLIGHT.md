# SKU HISTORICAL WAVE PREFLIGHT

Data: 2026-09-24  
Ambiente: homologacao  
Status: **BLOQUEADO AGUARDANDO POLITICA DE LEGADO**

## Fonte analisada

- 385 produtos/SKUs no no `produtos`.
- 7 aliases no no `sku_historico`.
- 382 produtos possuem cliente legado resolvido para um dos 59 clientes reconciliados.
- 3 produtos nao possuem `clienteKey` e permanecem bloqueados.
- Um dos tres bloqueados duplica o codigo legado `KUBPBA01 - 2` de um registro com cliente resolvido.
- Nenhum dos 392 registros foi gravado no cadastro de SKUs.

## Estado do alvo

- O tenant de homologacao possui zero SKUs antes desta onda.
- Os codigos legados nao seguem obrigatoriamente o formato atual `CAT3-CLI4-SEQ4`.
- O formato atual nao deve ser gerado retroativamente sem amostra/projeto e governanca contratual.
- Os registros legados nao possuem CGI assinado individualmente comprovado.

## Decisao obrigatoria

Escolher uma politica para os 382 produtos com cliente resolvido:

### Opcao A - legado autorizado

- Preservar o codigo historico como `codigo_interno`.
- Marcar `origem_contratual_status = legado_autorizado`.
- Marcar `legado_sem_cgi = true`.
- Manter ativo para vinculo de BOM, pedidos historicos e OPs migradas.
- Novos SKUs continuam seguindo exclusivamente a regra atual e nao reutilizam este caminho.

### Opcao B - legado bloqueado

- Preservar o codigo historico.
- Marcar `origem_contratual_status = revisao_pendente`.
- Marcar `legado_sem_cgi = true` e `bloqueado_por_cgi = true`.
- Nao disponibilizar para novos pedidos ate revisao individual.

## Registros que continuarao bloqueados em ambas as opcoes

- `DESODORANTE-ROLLON-ALGODAO`: cliente ausente.
- `DESODORANTE-ROLLON-LAVANDA`: cliente ausente.
- `KUBPBA01_-_2`: cliente ausente e codigo duplicado com `KUBPBA01-2`.

Os 7 aliases historicos serao tratados somente como mapa de alias depois que seus codigos de destino forem confirmados na onda escolhida.
