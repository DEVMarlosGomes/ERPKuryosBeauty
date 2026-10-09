# MATERIAL WAVE PREFLIGHT

Data: 2026-09-24  
Ambiente: homologacao  
Status: **BLOQUEADO AGUARDANDO APROVACAO DE CLASSIFICACAO**

## Planilha de decisao

- Fornecedores bloqueados preenchidos: 0 de 20.
- Materiais preenchidos: 0 de 939.
- SKUs preenchidos: 0 de 392.

Nenhum material ou SKU foi gravado nesta etapa.

## Distribuicao dos 939 materiais

| Familia legada | Dominio proposto | Quantidade | Confianca |
| --- | --- | ---: | --- |
| ES | Material ES | 326 | media |
| EP | Material EP | 192 | media |
| MPGR | Material MP | 141 | media |
| MPES | Fragrancia | 211 | media |
| ET | RT ou ES | 67 | baixa; decisao item a item |
| MU | sem dominio seguro | 2 | baixa |

## Subconjunto elegivel para uma regra global explicita

Com a aprovacao humana da regra de dominio e normalizacao de unidade, 846 registros podem formar uma onda controlada:

- 191 EP com unidade `un`;
- 324 ES com unidade `un`;
- 132 MPGR com unidade `kg` ou `L`;
- 199 MPES/fragrancias com unidade `kg`.

Os outros 93 permanecem bloqueados:

- 69 por dominio ambiguo ou desconhecido;
- 24 por unidade atipica para o dominio proposto.

## Dependencias adicionais

- Existem 570 referencias legadas de fornecedor dentro dos materiais.
- Essas referencias nao possuem vinculo confiavel por ID com os 383 fornecedores importados.
- A primeira carga de materiais deve preservar a referencia legada, mas nao criar vinculo operacional de fornecedor sem reconciliacao.
- A colecao alvo possui atualmente zero materiais e zero fragrancias; nenhum cadastro existente sera sobrescrito.

## Regra que exige autorizacao explicita

1. `EP -> materiais tipo2 EP`.
2. `ES -> materiais tipo2 ES`.
3. `MPGR -> materiais tipo2 MP`.
4. `MPES -> fragrancias`.
5. Unidade de compra vazia recebe a mesma unidade de estoque.
6. Referencias de fornecedor permanecem como metadado legado, sem vinculo operacional.
7. ET, MU e unidades atipicas continuam bloqueados para revisao manual.

Somente depois dessa aprovacao sera criado novo snapshot e executada uma onda transacional e reversivel em homologacao.
