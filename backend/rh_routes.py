from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from pymongo import ReturnDocument

from rbac import ADMIN_ONLY, require_roles


rh_router = APIRouter(prefix="/api/rh", tags=["rh"])

db = None
get_current_user = None
new_id = None
now_iso = None


def init_rh(database, get_current_user_fn, new_id_fn, now_iso_fn):
    global db, get_current_user, new_id, now_iso
    db = database
    get_current_user = get_current_user_fn
    new_id = new_id_fn
    now_iso = now_iso_fn


class CargoPayload(BaseModel):
    nome: str
    setor: str = ""
    nivel: str = ""
    descricao: str = ""
    ativo: bool = True


class ColaboradorPayload(BaseModel):
    nome: str
    cpf: str = ""
    email: str = ""
    telefone: str = ""
    cargo_id: str = ""
    cargo_nome: str = ""
    gestor_id: str = ""
    gestor_nome: str = ""
    sexo: str = ""
    tipo_contrato: str = "CLT"
    data_admissao: str = ""
    status: str = "Ativo"
    salario_base: float = 0
    vale_transporte: float = 0
    vale_alimentacao: float = 0
    dados_pessoais: Dict[str, Any] = Field(default_factory=dict)
    endereco: Dict[str, Any] = Field(default_factory=dict)
    emergencia: Dict[str, Any] = Field(default_factory=dict)
    observacoes: str = ""


class AvaliacaoPayload(BaseModel):
    colaborador_id: str
    periodo: str
    data: str = ""
    pontos_fortes: str = ""
    pontos_melhoria: str = ""
    comentario_colaborador: str = ""
    competencias: Dict[str, int] = Field(default_factory=dict)
    nota_geral: Optional[float] = None
    status: str = "Registrada"


class FeriasPayload(BaseModel):
    colaborador_id: str
    periodo_aquisitivo: str
    data_inicio: str
    data_fim: str
    observacoes: str = ""
    status: str = "Solicitada"


def _tenant(user: dict) -> str:
    return user.get("tenant_id") or "default"


def _clean(doc: Optional[dict]) -> Optional[dict]:
    if not doc:
        return None
    doc.pop("_id", None)
    return doc


def _parse_date(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return None


def _days_between(start: str, end: str) -> int:
    start_dt = _parse_date(start)
    end_dt = _parse_date(end)
    if not start_dt or not end_dt:
        return 0
    return max((end_dt.date() - start_dt.date()).days + 1, 0)


async def _current_user_and_admin(request: Request):
    user = await get_current_user(request)
    require_roles(user, ADMIN_ONLY)
    return user


@rh_router.get("/dashboard")
async def rh_dashboard(user: dict = Depends(_current_user_and_admin)):
    tenant_id = _tenant(user)
    colaboradores = await db.rh_colaboradores.find({"tenant_id": tenant_id}).to_list(1000)
    avaliacoes = await db.rh_avaliacoes.find({"tenant_id": tenant_id}).sort("created_at", -1).to_list(300)
    ferias = await db.rh_ferias.find({"tenant_id": tenant_id}).sort("created_at", -1).to_list(300)

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    ativos = [c for c in colaboradores if c.get("status", "Ativo") == "Ativo"]
    admissoes = [c for c in colaboradores if (_parse_date(c.get("data_admissao", "")) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff]
    desligamentos = [c for c in colaboradores if c.get("status") == "Desligado" and (_parse_date(c.get("data_desligamento", "")) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff]
    turnover = round((len(desligamentos) / max(len(ativos), 1)) * 100, 1)

    def group_count(field):
        result = {}
        for item in ativos:
            key = item.get(field) or "Nao informado"
            result[key] = result.get(key, 0) + 1
        return result

    custo_mensal = sum(float(c.get("salario_base") or 0) + float(c.get("vale_transporte") or 0) + float(c.get("vale_alimentacao") or 0) for c in ativos)
    notas = [a.get("nota_geral") for a in avaliacoes if isinstance(a.get("nota_geral"), (int, float))]
    pendentes_ferias = [f for f in ferias if f.get("status") in {"Solicitada", "Em aprovacao"}]
    alertas = []
    if pendentes_ferias:
        alertas.append(f"{len(pendentes_ferias)} solicitacao(oes) de ferias aguardando decisao.")
    if any(not c.get("cargo_id") and not c.get("cargo_nome") for c in ativos):
        alertas.append("Ha colaboradores ativos sem cargo vinculado.")

    return {
        "headcount_ativo": len(ativos),
        "admissoes_30d": len(admissoes),
        "desligamentos_30d": len(desligamentos),
        "turnover_30d": turnover,
        "por_sexo": group_count("sexo"),
        "por_tipo_contrato": group_count("tipo_contrato"),
        "custo_mensal": round(custo_mensal, 2),
        "media_avaliacoes": round(sum(notas) / len(notas), 1) if notas else 0,
        "ferias_pendentes": len(pendentes_ferias),
        "alertas": alertas,
    }


@rh_router.get("/cargos")
async def list_cargos(user: dict = Depends(_current_user_and_admin)):
    return [_clean(c) for c in await db.rh_cargos.find({"tenant_id": _tenant(user)}).sort("nome", 1).to_list(500)]


@rh_router.post("/cargos")
async def create_cargo(payload: CargoPayload, user: dict = Depends(_current_user_and_admin)):
    doc = payload.model_dump()
    doc.update({"id": new_id(), "tenant_id": _tenant(user), "created_at": now_iso(), "updated_at": now_iso(), "created_by": user.get("id")})
    await db.rh_cargos.insert_one(doc)
    return _clean(doc)


@rh_router.put("/cargos/{cargo_id}")
async def update_cargo(cargo_id: str, payload: CargoPayload, user: dict = Depends(_current_user_and_admin)):
    data = payload.model_dump()
    data.update({"updated_at": now_iso(), "updated_by": user.get("id")})
    result = await db.rh_cargos.find_one_and_update({"tenant_id": _tenant(user), "id": cargo_id}, {"$set": data}, return_document=ReturnDocument.AFTER)
    if not result:
        raise HTTPException(404, "Cargo nao encontrado.")
    return _clean(result)


@rh_router.delete("/cargos/{cargo_id}")
async def delete_cargo(cargo_id: str, user: dict = Depends(_current_user_and_admin)):
    await db.rh_cargos.delete_one({"tenant_id": _tenant(user), "id": cargo_id})
    return {"ok": True}


@rh_router.get("/colaboradores")
async def list_colaboradores(user: dict = Depends(_current_user_and_admin)):
    return [_clean(c) for c in await db.rh_colaboradores.find({"tenant_id": _tenant(user)}).sort("nome", 1).to_list(1000)]


@rh_router.post("/colaboradores")
async def create_colaborador(payload: ColaboradorPayload, user: dict = Depends(_current_user_and_admin)):
    doc = payload.model_dump()
    doc.update({"id": new_id(), "tenant_id": _tenant(user), "created_at": now_iso(), "updated_at": now_iso(), "created_by": user.get("id")})
    await db.rh_colaboradores.insert_one(doc)
    return _clean(doc)


@rh_router.put("/colaboradores/{colaborador_id}")
async def update_colaborador(colaborador_id: str, payload: ColaboradorPayload, user: dict = Depends(_current_user_and_admin)):
    data = payload.model_dump()
    data.update({"updated_at": now_iso(), "updated_by": user.get("id")})
    result = await db.rh_colaboradores.find_one_and_update({"tenant_id": _tenant(user), "id": colaborador_id}, {"$set": data}, return_document=ReturnDocument.AFTER)
    if not result:
        raise HTTPException(404, "Colaborador nao encontrado.")
    return _clean(result)


@rh_router.post("/colaboradores/{colaborador_id}/desligar")
async def desligar_colaborador(colaborador_id: str, user: dict = Depends(_current_user_and_admin)):
    result = await db.rh_colaboradores.find_one_and_update(
        {"tenant_id": _tenant(user), "id": colaborador_id},
        {"$set": {"status": "Desligado", "data_desligamento": now_iso(), "updated_at": now_iso(), "updated_by": user.get("id")}},
        return_document=ReturnDocument.AFTER,
    )
    if not result:
        raise HTTPException(404, "Colaborador nao encontrado.")
    return _clean(result)


@rh_router.delete("/colaboradores/{colaborador_id}")
async def delete_colaborador(colaborador_id: str, user: dict = Depends(_current_user_and_admin)):
    await db.rh_colaboradores.delete_one({"tenant_id": _tenant(user), "id": colaborador_id})
    return {"ok": True}


@rh_router.get("/avaliacoes")
async def list_avaliacoes(user: dict = Depends(_current_user_and_admin)):
    return [_clean(a) for a in await db.rh_avaliacoes.find({"tenant_id": _tenant(user)}).sort("created_at", -1).to_list(1000)]


@rh_router.post("/avaliacoes")
async def create_avaliacao(payload: AvaliacaoPayload, user: dict = Depends(_current_user_and_admin)):
    doc = payload.model_dump()
    if doc.get("nota_geral") is None and doc.get("competencias"):
        notas = [int(v) for v in doc["competencias"].values() if isinstance(v, int)]
        doc["nota_geral"] = round(sum(notas) / len(notas), 1) if notas else 0
    doc.update({"id": new_id(), "tenant_id": _tenant(user), "created_at": now_iso(), "updated_at": now_iso(), "created_by": user.get("id")})
    await db.rh_avaliacoes.insert_one(doc)
    return _clean(doc)


@rh_router.put("/avaliacoes/{avaliacao_id}")
async def update_avaliacao(avaliacao_id: str, payload: AvaliacaoPayload, user: dict = Depends(_current_user_and_admin)):
    data = payload.model_dump()
    data.update({"updated_at": now_iso(), "updated_by": user.get("id")})
    result = await db.rh_avaliacoes.find_one_and_update({"tenant_id": _tenant(user), "id": avaliacao_id}, {"$set": data}, return_document=ReturnDocument.AFTER)
    if not result:
        raise HTTPException(404, "Avaliacao nao encontrada.")
    return _clean(result)


@rh_router.delete("/avaliacoes/{avaliacao_id}")
async def delete_avaliacao(avaliacao_id: str, user: dict = Depends(_current_user_and_admin)):
    await db.rh_avaliacoes.delete_one({"tenant_id": _tenant(user), "id": avaliacao_id})
    return {"ok": True}


@rh_router.get("/ferias")
async def list_ferias(user: dict = Depends(_current_user_and_admin)):
    return [_clean(f) for f in await db.rh_ferias.find({"tenant_id": _tenant(user)}).sort("created_at", -1).to_list(1000)]


@rh_router.post("/ferias")
async def create_ferias(payload: FeriasPayload, user: dict = Depends(_current_user_and_admin)):
    doc = payload.model_dump()
    doc.update({"id": new_id(), "tenant_id": _tenant(user), "dias": _days_between(doc["data_inicio"], doc["data_fim"]), "created_at": now_iso(), "updated_at": now_iso(), "created_by": user.get("id")})
    await db.rh_ferias.insert_one(doc)
    return _clean(doc)


@rh_router.put("/ferias/{ferias_id}")
async def update_ferias(ferias_id: str, payload: FeriasPayload, user: dict = Depends(_current_user_and_admin)):
    data = payload.model_dump()
    data.update({"dias": _days_between(data["data_inicio"], data["data_fim"]), "updated_at": now_iso(), "updated_by": user.get("id")})
    result = await db.rh_ferias.find_one_and_update({"tenant_id": _tenant(user), "id": ferias_id}, {"$set": data}, return_document=ReturnDocument.AFTER)
    if not result:
        raise HTTPException(404, "Solicitacao de ferias nao encontrada.")
    return _clean(result)


@rh_router.post("/ferias/{ferias_id}/{acao}")
async def decide_ferias(ferias_id: str, acao: str, user: dict = Depends(_current_user_and_admin)):
    status = {"aprovar": "Aprovada", "reprovar": "Reprovada", "cancelar": "Cancelada"}.get(acao)
    if not status:
        raise HTTPException(400, "Acao invalida.")
    result = await db.rh_ferias.find_one_and_update(
        {"tenant_id": _tenant(user), "id": ferias_id},
        {"$set": {"status": status, "decidido_em": now_iso(), "decidido_por": user.get("id"), "updated_at": now_iso()}},
        return_document=ReturnDocument.AFTER,
    )
    if not result:
        raise HTTPException(404, "Solicitacao de ferias nao encontrada.")
    return _clean(result)


@rh_router.delete("/ferias/{ferias_id}")
async def delete_ferias(ferias_id: str, user: dict = Depends(_current_user_and_admin)):
    await db.rh_ferias.delete_one({"tenant_id": _tenant(user), "id": ferias_id})
    return {"ok": True}
