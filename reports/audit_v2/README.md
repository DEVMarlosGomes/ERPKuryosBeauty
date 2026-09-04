# Auditoria V2 - Reports

Esta pasta guarda saidas dry-run e evidencias geradas durante a execucao da Auditoria V2.

Arquivos esperados:

- `duplicate_clients_*.json`
- `material_links_*.json`
- `sku_integrity_*.json`
- `order_integrity_*.json`

Regra operacional: scripts de auditoria devem rodar em modo somente leitura por padrao. Qualquer correcao de dados precisa de flag explicita `--apply` e plano revisavel.
