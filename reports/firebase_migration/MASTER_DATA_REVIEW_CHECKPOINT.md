# Cadastros bloqueados — checkpoint de homologação

Data: 2026-09-24  
Status: **APLICADO E VERIFICADO SOMENTE EM HOMOLOGAÇÃO**

## Resultado

- 20 fornecedores bloqueados incluídos na fila de saneamento.
- 93 materiais bloqueados incluídos na fila de saneamento.
- 3 SKUs bloqueados incluídos na fila de saneamento.
- Total de 116 registros em `legacy_master_data_reviews`.
- Todos permanecem com `operational_eligible = false`, `activation_status = bloqueado` e `review_status = pendente_revisao`.

## Isolamento operacional

As contagens ficaram iguais antes e depois da onda:

- `compras_fornecedores`: 383;
- `materiais`: 647;
- `fragrancias`: 199;
- `skus`: 382.

As 107 coleções anteriores mantiveram contagem, hash canônico de documentos e fingerprint dos índices sem divergências.

## Snapshot e retorno

- Snapshot: `C:\Users\MARLOS\.kuryos\backups\kuryos-erp-hml-pre-master-data-review-v2-20260924.archive.gz`
- SHA-256: `fba29197578e303ab52ca5dc2425ec8f5a2da2ff9df6f1fe741f86ac5c898a41`
- Conteúdo: 107 coleções e 13.164 documentos.
- Restauração integral: verificada.
- Rollback seletivo: verificado em banco local descartável; os 116 documentos foram removidos e o banco de ensaio foi apagado.

## Próxima decisão humana

1. Fornecedores: informar CNPJ válido ou escolher a consolidação dos duplicados.
2. Materiais: escolher domínio MP, EP, ES, RT ou fragrância e corrigir unidade.
3. SKUs: resolver cliente e a colisão do código legado.

Nenhum desses registros deve ser promovido automaticamente.

## Fluxo de decisão disponível no ERP

Na tela `Cadastros > Revisão legado > Cadastros bloqueados da migração`, materiais possuem agora duas etapas independentes:

1. **Classificar**: selecionar MP, EP, ES, RT ou fragrância, corrigir nome/unidades e registrar justificativa de aprovação ou reprovação.
2. **Promover**: disponível somente após aprovação; cria o cadastro operacional em transação e gera o próximo código pelo contador oficial.

EP, ES e RT exigem unidade de estoque `un`; fragrância exige unidade de massa ou volume. A promoção não cria saldo, lote, fornecedor, BOM nem movimentação de estoque.

## Fluxo de fornecedores disponível no ERP

Os 20 fornecedores bloqueados também possuem resolução humana em duas etapas na mesma tela:

1. **Resolver**: escolher entre criar um fornecedor com CNPJ válido/corrigido ou consolidar o legado em um fornecedor operacional existente, sempre com justificativa.
2. **Confirmar**: disponível somente depois da aprovação; cria o fornecedor ou registra a consolidação dentro de uma transação MongoDB.

A criação usa o contador oficial `compras_fornecedores`, impede CNPJ duplicado e inicia a homologação do fornecedor como `nao_iniciada`. A consolidação não cria cópia nem altera o fornecedor de destino. Nenhum fornecedor foi aprovado ou promovido automaticamente durante esta implementação.

Validações executadas em 2026-09-25:

- backend: 19 testes aprovados, incluindo validação de CNPJ e consolidação sem duplicidade;
- frontend: build Vite concluído;
- produção: não acessada e não alterada.

Uma nova verificação somente leitura confirmou os 116 registros ainda bloqueados/não operacionais e as quatro coleções operacionais sem alteração de contagem. O comparador integral do snapshot registrou deriva de conteúdo em `kickoffs` e `system_status` (contagens e índices preservados), gerada pelo uso normal da HML após o snapshot; não houve falha de hash dos 116 registros nem promoção automática.

## Fluxo dos SKUs bloqueados disponível no ERP

Os 3 SKUs sem cliente resolvido podem ser tratados na mesma fila, também em duas etapas:

1. **Resolver**: selecionar o cliente correto e revisar código/nome para criar o SKU, ou consolidar o registro legado em um SKU operacional existente.
2. **Confirmar**: cria ou consolida em transação somente depois da aprovação humana.

Quando criado, o documento recebe `legacy_authorized = true`, `legado_sem_cgi = true` e a regra de migração `human_review_legacy_sku_promotion_v1`. Essa exceção é exclusiva dos dados históricos revisados e não altera a geração de novos SKUs, que continua vinculada à assinatura do CGI. Os dados legados indicados como inativos permanecem inativos.

Validação final desta etapa em 2026-09-25:

- 21 testes de backend aprovados;
- frontend compilado com 2.488 módulos;
- rotas de decisão e promoção de SKU carregadas na HML;
- frontend HTTP 200 e backend ativo;
- nenhum dos 3 SKUs foi promovido automaticamente;
- produção não acessada e não alterada.
