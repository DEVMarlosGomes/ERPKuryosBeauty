#!/usr/bin/env python3
"""Read-only preflight for remaining supplemental Firebase history."""
from __future__ import annotations
import argparse,hashlib,json
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
from apply_firebase_clients_hml import SOURCE_SHA

NODES={"especificacoes":("specification",213),"programacao":("production_schedule",51),"paradas_historico":("production_stop",141),"intervalosApontados":("reported_break",13),"turnosEncerrados":("closed_shift",34),"perdas":("production_loss_group",22),"precos_venda":("sale_price",110),"processos_cotacao":("quotation_process",13)}
EXPECTED={kind:count for _,(kind,count) in NODES.items()}
def clean(v:Any)->str:return str(v or "").strip()
def vals(v:Any)->list[Any]:return list(v.values()) if isinstance(v,dict) else v if isinstance(v,list) else []

def main()->int:
 p=argparse.ArgumentParser();p.add_argument("--source",type=Path,required=True);p.add_argument("--sku-map",type=Path,default=Path("reports/firebase_migration/SKU_ID_MAP_APPLIED.json"));p.add_argument("--material-map",type=Path,default=Path("reports/firebase_migration/MATERIAL_ID_MAP_APPLIED.json"));p.add_argument("--json-output",type=Path,required=True);p.add_argument("--markdown-output",type=Path,required=True);a=p.parse_args()
 raw_bytes=a.source.read_bytes()
 if hashlib.sha256(raw_bytes).hexdigest()!=SOURCE_SHA:raise RuntimeError("Firebase source hash mismatch")
 source=json.loads(raw_bytes.decode("utf-8"));sku_doc=json.loads(a.sku_map.read_text(encoding="utf-8"));mat_doc=json.loads(a.material_map.read_text(encoding="utf-8"))
 skus={clean(x.get(k)).upper() for x in sku_doc.get("entries",[]) for k in ("legacy_id","legacy_sku","target_codigo_interno") if clean(x.get(k))};mats={clean(x.get(k)).upper() for x in mat_doc.get("entries",[]) for k in ("legacy_id","target_codigo_interno") if clean(x.get(k))}
 records=[];resolution=Counter();counts={}
 for node,(kind,expected) in NODES.items():
  rows=source.get(node) or {};counts[kind]=len(rows)
  if len(rows)!=expected:raise RuntimeError(f"Unexpected {node} count: {len(rows)}")
  for key,payload in sorted(rows.items()):
   blockers=[];refs=[]
   if node=="especificacoes":
    code=clean(payload.get("codProduto")).upper();refs=[code]
    if code not in skus:blockers.append("sku_unresolved")
   elif node=="precos_venda":
    code=clean(payload.get("sku") or key).upper();refs=[code]
    if code not in skus:blockers.append("sku_unresolved")
   elif node=="processos_cotacao":
    refs=[clean(x.get("materialCodigo")).upper() for x in vals(payload.get("itens"))]
    blockers.extend(f"material_unresolved:{x or 'sem_codigo'}" for x in refs if x not in mats)
   elif node=="programacao":
    refs=[clean(slot.get("sku")).upper() for hour in vals(payload) for slot in vals(hour) if isinstance(slot,dict) and clean(slot.get("sku"))]
    blockers.extend(f"sku_unresolved:{x}" for x in refs if x not in skus)
   classification="historical_archive_ready" if not blockers else "manual_review";resolution[(kind,classification)]+=1
   records.append({"source_node":node,"source_key":str(key),"record_type":kind,"legacy_status":payload.get("status") if isinstance(payload,dict) else None,"reference_codes":sorted(set(refs)),"blockers":sorted(set(blockers)),"classification":classification})
 if counts!=EXPECTED:raise RuntimeError(f"Unexpected counts: {counts}")
 report={"generated_at":datetime.now(timezone.utc).isoformat(),"mode":"READ_ONLY_HML_RECONCILIATION","source_sha256":SOURCE_SHA,"production_written":False,"homologation_written":False,"counts":counts,"total":len(records),"classifications":{f"{k[0]}:{k[1]}":v for k,v in resolution.items()},"records":records,"decision_gate":{"status":"READY_FOR_ISOLATED_HML_REVIEW","operational_replay_allowed":False}}
 a.json_output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");a.markdown_output.write_text("\n".join(["# Históricos complementares - preflight HML","",f"Gerado em: {report['generated_at']}","",f"Total: {len(records)}",*[f"- `{k}`: {v}" for k,v in counts.items()],"","Nenhum registro poderá recalcular preço, programação, perda ou cotação nesta onda."])+"\n",encoding="utf-8");print(json.dumps({"status":"PREFLIGHT_VALID","total":len(records),"counts":counts,"classifications":report["classifications"]},ensure_ascii=False));return 0
if __name__=="__main__":raise SystemExit(main())
