# PCP Delta Slice 1 Summary

Data: 2026-09-11

Feature flag: `pcp_quantity_planning_v2`.

Resultado: GO COM RESSALVAS.

Testes:
- Backend focado alertas PCP: `9 passed`.
- Backend focado WMS/recebimento: `10 passed`.
- Backend focado materiais fiscais/WMS: `14 passed`.
- Backend focado pacote comercial: `5 passed`.
- Backend focado anexos unificados: `16 passed`.
- Backend focado card governance: `5 passed`.
- Backend completo: `121 passed, 278 skipped`.
- Frontend build: `Compiled successfully`.

Arquivos alterados:
- `backend/orders_routes.py`
- `backend/pcp_routes.py`
- `backend/estoque_routes.py`
- `backend/recebimento_routes.py`
- `backend/materiais_routes.py`
- `backend/crm_routes.py`
- `backend/pd_routes.py`
- `backend/server.py`
- `backend/tests/test_card_governance_unit.py`
- `backend/tests/test_unified_attachments_unit.py`
- `backend/tests/test_pcp_allocations_unit.py`
- `backend/tests/test_pcp_alerts_unit.py`
- `backend/tests/test_commercial_packages_unit.py`
- `backend/tests/test_materiais_fiscal_defaults_unit.py`
- `backend/tests/test_wms_recebimento_unit.py`
- `frontend/src/App.js`
- `frontend/src/components/DynamicSidebar.js`
- `frontend/src/pages/OPDetail.js`
- `frontend/src/pages/PCPQuantityPlanningPage.js`
- `docs/PCP_DELTA_REFRESH_2026_09.md`
- `docs/PCP_DELTA_IMPLEMENTATION_REPORT.md`
- `docs/PCP_DELTA_API_CHANGES.md`
- `docs/PCP_DELTA_DATA_CHANGES.md`
- `docs/PCP_DELTA_ROLLBACK.md`

Slices cobertos:
- Slice 1: `pcp_allocations` + Pedido -> N OPs por item/saldo.
- Slice 2: UI Planejamento > Quantidades.
- Slice 3: backend inicial de separacao FEFO por OP.
- Slice 4: UI de separacao FEFO no Detalhe da OP.
- Slice 5: backend inicial de alertas PCP com tolerancia e repique.
- Slice 6: backend inicial de inventario ciclico/contagem cega WMS.
- Slice 7: backend inicial de descarte/logistica reversa WMS.
- Slice 8: backend inicial de lote interno/idempotencia de recebimento.
- Slice 9: backend inicial de defaults fiscais de material.
- Slice 10: backend inicial de pacote comercial por aprovacao de amostra.
- Slice 11: backend inicial de anexos unificados em object storage.
- Slice 12: backend inicial de V21 card governance.
