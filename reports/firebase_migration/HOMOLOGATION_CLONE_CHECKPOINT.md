# HOMOLOGATION CLONE CHECKPOINT

Data: 2026-09-24

## Resultado

- Origem: banco `kuryos`, acessado exclusivamente com `read@kuryos`.
- Destino: banco `kuryos_erp_homologacao`.
- Coleções na origem: 101.
- Coleções na homologação: 101.
- Documentos na origem: 9.041.
- Documentos na homologação: 9.041.
- Coleções ausentes ou extras: nenhuma.
- Divergências de contagem: nenhuma.
- Divergências de hash do conteúdo: nenhuma.
- Divergências de índices: nenhuma.
- Falhas informadas pelo `mongorestore`: zero.
- Arquivo temporário removido após validação: sim.
- Escritas na produção: nenhuma; a credencial não possui permissão de escrita.

## Tenants encontrados

1. `a1534e89-bbfa-483f-ac0b-8d6dbf6bab22` — Kuryos Demo
   - 14 usuários
   - 15 clientes CRM
   - 28 projetos CRM
   - 30 amostras CRM
   - 95 solicitações P&D
   - 95 desenvolvimentos P&D
   - 16 pedidos
   - 1 OP
   - 3.320 registros de auditoria

2. `cb774e96-f664-402e-bda4-2abae2eecf55` — Kuryos
   - 1 usuário
   - nenhum registro operacional nas coleções avaliadas

3. `11465988-6b8e-43a3-a552-a87d4af38641` — Kuryos (nome com espaço final)
   - 1 usuário
   - 2 registros de auditoria
   - nenhum registro operacional nas demais coleções avaliadas

## Próxima barreira

Confirmar explicitamente o tenant que receberá a reconciliação Firebase. Pelos dados persistidos, o candidato operacional é `a1534e89-bbfa-483f-ac0b-8d6dbf6bab22`.

Nenhuma transformação ou aplicação dos dados Firebase foi executada neste checkpoint.
