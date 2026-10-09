#!/usr/bin/env python3
"""Read-only coverage preflight for the remaining Firebase top-level nodes."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from apply_firebase_clients_hml import SOURCE_SHA


EXPECTED = {
    "ajustes_planejamento": 2,
    "comercial_eventos": 1,
    "config": 32,
    "contadores_lote_interno": 1,
    "email_notifications_state": 2,
    "emails_diretoria": 2,
    "estado_linhas": 3,
    "estoque": 95,
    "estrutura_ruas": 19,
    "historico_materiais": 901,
    "insumos": 1,
    "movimentos_estoque": 72,
    "notificacoes_comercial": 8,
    "notificacoes_op_encerrada": 41,
    "parametros_pa": 2,
    "registros": 376,
}

NO_REPLAY_NODES = {
    "config": "configuracao_legada_nao_deve_sobrescrever_hml",
    "contadores_lote_interno": "contador_legado_nao_deve_ser_reativado",
    "email_notifications_state": "estado_de_envio_nao_deve_ser_reativado",
    "estoque": "saldo_agregado_nao_conciliado_com_ledger",
    "movimentos_estoque": "movimento_legado_ambiguo_nao_deve_afetar_saldo",
    "notificacoes_comercial": "notificacao_historica_nao_deve_ser_reenviada",
    "notificacoes_op_encerrada": "notificacao_historica_nao_deve_ser_reenviada",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    args = parser.parse_args()

    raw = args.source.read_bytes()
    source_hash = hashlib.sha256(raw).hexdigest()
    if source_hash != SOURCE_SHA:
        raise RuntimeError("Firebase source hash mismatch")
    source = json.loads(raw.decode("utf-8"))

    records = []
    counts = {}
    dispositions = Counter()
    for node, expected in EXPECTED.items():
        value = source.get(node)
        if not isinstance(value, dict):
            raise RuntimeError(f"Expected object node: {node}")
        counts[node] = len(value)
        if len(value) != expected:
            raise RuntimeError(f"Unexpected {node} count: {len(value)} != {expected}")
        for source_key, payload in sorted(value.items()):
            disposition = "excluded_no_replay" if node in NO_REPLAY_NODES else "historical_reference"
            reason = NO_REPLAY_NODES.get(node, "referencia_historica_isolada")
            dispositions[disposition] += 1
            records.append({
                "source_node": node,
                "source_key": str(source_key),
                "source_value_type": type(payload).__name__,
                "source_bytes": len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")),
                "disposition": disposition,
                "disposition_reason": reason,
            })

    total = sum(EXPECTED.values())
    if counts != EXPECTED or len(records) != total:
        raise RuntimeError("Final source coverage count mismatch")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "READ_ONLY_FINAL_SOURCE_COVERAGE",
        "source_sha256": SOURCE_SHA,
        "production_written": False,
        "homologation_written": False,
        "counts": counts,
        "total": total,
        "dispositions": dict(dispositions),
        "records": records,
        "decision_gate": {
            "status": "READY_FOR_ISOLATED_HML_ARCHIVE",
            "operational_replay_allowed": False,
            "operational_collections_may_change": False,
        },
    }
    args.json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Cobertura final da fonte Firebase — preflight HML",
        "",
        f"Gerado em: {report['generated_at']}",
        "",
        f"Total de unidades de arquivo: **{total}**.",
        "",
        "## Disposição",
        "",
        *[f"- `{key}`: {value}" for key, value in sorted(dispositions.items())],
        "",
        "## Nós cobertos",
        "",
        *[f"- `{key}`: {value}" for key, value in counts.items()],
        "",
        "Todos os documentos permanecerão isolados, bloqueados e sem replay operacional.",
        "Estoque agregado, movimentos, contadores, configurações e estados de notificação não serão aplicados ao ERP.",
    ]
    args.markdown_output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PREFLIGHT_VALID", "total": total, "dispositions": dict(dispositions)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
