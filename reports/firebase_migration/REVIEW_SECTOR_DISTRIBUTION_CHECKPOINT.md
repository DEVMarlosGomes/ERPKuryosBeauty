# Distribuição das revisões legadas por setor — checkpoint HML

Data: 2026-09-25  
Status: **APLICADO E VERIFICADO SOMENTE EM HOMOLOGAÇÃO**

## Auditoria de origem

- 5.234 documentos auditados nas 12 coleções de revisão legada.
- 0 IDs duplicados.
- 0 identidades de origem (`source_node + source_group_key + source_key`) duplicadas.
- 289 documentos de corte de estoque já possuíam encaminhamento válido e foram preservados.
- 4.945 documentos receberam destino nesta onda.
- Nenhuma cópia de documento foi criada.

## Destino atual

| Setor | Quantidade | Conteúdo principal |
|---|---:|---|
| PCP | 2.071 | OPs, programação, paradas, perdas, turnos, registros e estados de linha |
| Logística | 1.338 | Endereços, estoque histórico, estrutura de ruas, materiais e movimentos históricos |
| Comercial | 572 | Pedidos/itens comerciais, preços de venda, eventos e notificações comerciais |
| Cadastros | 343 | Materiais, SKUs, BOMs e contador legado para conferência |
| Expedição | 338 | Expedições comerciais históricas |
| Qualidade | 270 | Lotes, recebimentos, conferências de PA, não conformidades e especificações |
| P&D | 197 | Fórmulas legadas |
| Compras | 53 | Fornecedores, solicitações/pedidos de compra e cotações |
| Administração/TI | 36 | Configurações e estados históricos de e-mail, sem replay |
| RH | 16 | 13 usuários em revisão e 3 cargos já promovidos |

Total: **5.234**.

## Encaminhamentos seguintes

- Fornecedor: Compras → Cadastros.
- Fórmula: P&D → Cadastros.
- BOM: Cadastros → Compras.
- Pedido comercial: Comercial → PCP.
- Lote legado: Qualidade → Logística.
- Recebimento legado: Qualidade → Logística.
- Especificação e parâmetro de PA: Qualidade → Cadastros.

Cada documento possui somente um `assigned_sector`. O eventual próximo responsável fica em `next_sector`, sem replicar o registro.

## Segurança e retorno

- Snapshot anterior: `C:\Users\MARLOS\.kuryos\backups\kuryos-erp-hml-pre-review-sector-distribution-20260925.archive.gz`
- SHA-256: `8578daeb8c7eaadf4e172c7ffd4a5f578fedaa94e78b20d5e5643be3e5ab42b3`
- Snapshot restaurado: 117 coleções e 16.129 documentos, sem falhas.
- 105 coleções não envolvidas permaneceram com documentos e índices idênticos.
- Hashes dos 4.945 documentos alterados conferidos.
- Zero divergências de rota e zero revisões pendentes habilitadas operacionalmente.
- Rollback ensaiado localmente: 4.945 documentos restaurados ao estado anterior, sem falhas; banco descartável removido.
- Produção não foi acessada nem alterada.

## Evidências

- Plano registro a registro: `REVIEW_SECTOR_AUDIT_PREFLIGHT.json`.
- Aplicação: `REVIEW_SECTOR_DISTRIBUTION_APPLY.json`.
- Verificação: `REVIEW_SECTOR_DISTRIBUTION_VERIFY.json`.
- Ensaio de retorno: `REVIEW_SECTOR_DISTRIBUTION_ROLLBACK_DRILL.json`.
