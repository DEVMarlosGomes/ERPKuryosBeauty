"""Ledger imutavel de estoque por lote.

Movimentos fisicos e eventos de reserva compartilham a colecao
``estoque_movimentos_lote``. O saldo materializado continua em
``estoque_saldos_lote`` para consultas rapidas, mas toda alteracao relevante
deve deixar um evento auditavel neste ledger.
"""

from typing import Any, Dict, Optional

from fastapi import HTTPException
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError


def _as_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def saldo_quantidade_fisica(saldo: Dict[str, Any]) -> float:
    value = saldo.get("quantidade")
    if value is None:
        value = saldo.get("quantidade_atual")
    return _as_float(value)


def saldo_quantidade_reservada(saldo: Dict[str, Any]) -> float:
    return max(_as_float(saldo.get("quantidade_reservada")), 0.0)


def saldo_quantidade_disponivel(saldo: Dict[str, Any]) -> float:
    return max(saldo_quantidade_fisica(saldo) - saldo_quantidade_reservada(saldo), 0.0)


async def create_stock_ledger_indexes(database) -> None:
    ledger = database.estoque_movimentos_lote
    await ledger.create_index([("tenant_id", 1), ("saldo_lote_id", 1), ("created_at", -1)])
    await ledger.create_index([("tenant_id", 1), ("op_id", 1), ("natureza", 1), ("created_at", -1)])
    await ledger.create_index(
        [("tenant_id", 1), ("idempotency_key", 1)],
        unique=True,
        partialFilterExpression={"idempotency_key": {"$type": "string"}},
    )


async def append_lot_ledger_event(
    database,
    *,
    new_id_fn,
    now_iso_fn,
    tenant_id: str,
    saldo: Dict[str, Any],
    natureza: str,
    evento: str,
    quantidade: float = 0.0,
    quantidade_delta: float = 0.0,
    reserva_delta: float = 0.0,
    quantidade_antes: Optional[float] = None,
    quantidade_depois: Optional[float] = None,
    motivo: str = "",
    documento: str = "",
    referencia: str = "",
    op_id: Optional[str] = None,
    wms_separacao_id: Optional[str] = None,
    usuario: Optional[Dict[str, Any]] = None,
    idempotency_key: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    user = usuario or {}
    event = {
        "id": new_id_fn(),
        "tenant_id": tenant_id,
        "saldo_lote_id": saldo.get("id"),
        "item_id": saldo.get("item_id"),
        "item_nome": saldo.get("item_nome", ""),
        "codigo_item": saldo.get("codigo_item", ""),
        "lote": saldo.get("lote", ""),
        "endereco_id": saldo.get("endereco_id"),
        "endereco_codigo": saldo.get("endereco_codigo", ""),
        "setor": saldo.get("setor", ""),
        "natureza": natureza,
        "evento": evento,
        # Campos legados preservados para o kardex existente.
        "tipo": evento,
        "direcao": "entrada" if quantidade_delta > 0 else "saida" if quantidade_delta < 0 else "neutro",
        "quantidade": abs(_as_float(quantidade)),
        "quantidade_delta": _as_float(quantidade_delta),
        "reserva_delta": _as_float(reserva_delta),
        "unidade": saldo.get("unidade", "un"),
        "quantidade_antes": quantidade_antes,
        "quantidade_depois": quantidade_depois,
        "motivo": motivo,
        "documento": documento,
        "referencia": referencia,
        "op_id": op_id,
        "wms_separacao_id": wms_separacao_id,
        "usuario": user.get("name", ""),
        "usuario_id": user.get("id", ""),
        "idempotency_key": idempotency_key,
        "metadata": metadata or {},
        "created_at": now_iso_fn(),
    }
    if not idempotency_key:
        event.pop("idempotency_key")
    await database.estoque_movimentos_lote.insert_one(event)
    return {k: v for k, v in event.items() if k != "_id"}


async def reservar_saldo_lote(
    database,
    *,
    new_id_fn,
    now_iso_fn,
    tenant_id: str,
    saldo_lote_id: str,
    quantidade: float,
    op_id: str,
    wms_separacao_id: str,
    usuario: Dict[str, Any],
    material_key: str = "",
) -> Dict[str, Any]:
    quantidade = _as_float(quantidade)
    if quantidade <= 0:
        raise HTTPException(status_code=422, detail="Quantidade de reserva deve ser maior que zero.")

    key = f"reserva:{wms_separacao_id}:{saldo_lote_id}:{material_key}"
    existing = await database.estoque_movimentos_lote.find_one(
        {"tenant_id": tenant_id, "idempotency_key": key}, {"_id": 0}
    )
    if existing:
        saldo = await database.estoque_saldos_lote.find_one(
            {"id": saldo_lote_id, "tenant_id": tenant_id}, {"_id": 0}
        )
        return saldo or {}

    physical_expr = {"$ifNull": ["$quantidade", {"$ifNull": ["$quantidade_atual", 0]}]}
    reserved_expr = {"$ifNull": ["$quantidade_reservada", 0]}
    updated = await database.estoque_saldos_lote.find_one_and_update(
        {
            "id": saldo_lote_id,
            "tenant_id": tenant_id,
            "$expr": {"$gte": [{"$subtract": [physical_expr, reserved_expr]}, quantidade]},
        },
        {
            "$inc": {"quantidade_reservada": quantidade},
            "$set": {"reserva_status": "reservado", "updated_at": now_iso_fn()},
        },
        return_document=ReturnDocument.AFTER,
        projection={"_id": 0},
    )
    if not updated:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "saldo_insuficiente_para_reserva",
                "message": "Saldo disponivel insuficiente; outra OP pode ter reservado o lote.",
                "saldo_lote_id": saldo_lote_id,
                "quantidade": quantidade,
            },
        )

    try:
        await append_lot_ledger_event(
            database,
            new_id_fn=new_id_fn,
            now_iso_fn=now_iso_fn,
            tenant_id=tenant_id,
            saldo=updated,
            natureza="reserva",
            evento="RESERVA_CRIADA",
            quantidade=quantidade,
            reserva_delta=quantidade,
            motivo=f"Reserva de material para OP {op_id}",
            referencia=wms_separacao_id,
            op_id=op_id,
            wms_separacao_id=wms_separacao_id,
            usuario=usuario,
            idempotency_key=key,
            metadata={"material_key": material_key},
        )
    except DuplicateKeyError:
        # Uma confirmacao concorrente venceu a corrida: desfaz apenas este incremento.
        await database.estoque_saldos_lote.update_one(
            {"id": saldo_lote_id, "tenant_id": tenant_id},
            {"$inc": {"quantidade_reservada": -quantidade}, "$set": {"updated_at": now_iso_fn()}},
        )
    return updated


async def liberar_reserva_saldo_lote(
    database,
    *,
    new_id_fn,
    now_iso_fn,
    tenant_id: str,
    saldo_lote_id: str,
    quantidade: float,
    op_id: str,
    wms_separacao_id: str,
    usuario: Dict[str, Any],
    motivo: str,
    material_key: str = "",
) -> Dict[str, Any]:
    quantidade = _as_float(quantidade)
    key = f"liberacao:{wms_separacao_id}:{saldo_lote_id}:{material_key}"
    existing = await database.estoque_movimentos_lote.find_one(
        {"tenant_id": tenant_id, "idempotency_key": key}, {"_id": 0}
    )
    if existing:
        return existing

    updated = await database.estoque_saldos_lote.find_one_and_update(
        {
            "id": saldo_lote_id,
            "tenant_id": tenant_id,
            "$expr": {"$gte": [{"$ifNull": ["$quantidade_reservada", 0]}, quantidade]},
        },
        {
            "$inc": {"quantidade_reservada": -quantidade},
            "$set": {"updated_at": now_iso_fn()},
        },
        return_document=ReturnDocument.AFTER,
        projection={"_id": 0},
    )
    if not updated:
        raise HTTPException(status_code=409, detail="Reserva do lote insuficiente para liberacao.")

    if saldo_quantidade_reservada(updated) <= 0.000001:
        await database.estoque_saldos_lote.update_one(
            {"id": saldo_lote_id, "tenant_id": tenant_id},
            {"$set": {"reserva_status": "livre", "updated_at": now_iso_fn()}},
        )
        updated["reserva_status"] = "livre"

    return await append_lot_ledger_event(
        database,
        new_id_fn=new_id_fn,
        now_iso_fn=now_iso_fn,
        tenant_id=tenant_id,
        saldo=updated,
        natureza="reserva",
        evento="RESERVA_LIBERADA",
        quantidade=quantidade,
        reserva_delta=-quantidade,
        motivo=motivo,
        referencia=wms_separacao_id,
        op_id=op_id,
        wms_separacao_id=wms_separacao_id,
        usuario=usuario,
        idempotency_key=key,
        metadata={"material_key": material_key},
    )


async def consumir_reserva_saldo_lote(
    database,
    *,
    new_id_fn,
    now_iso_fn,
    tenant_id: str,
    saldo_lote_id: str,
    quantidade: float,
    op_id: str,
    wms_separacao_id: str,
    apontamento_id: str,
    usuario: Dict[str, Any],
    material_key: str = "",
    op_item_idx: int = 0,
) -> Dict[str, Any]:
    """Converte empenho em consumo, baixando fisico e reservado juntos."""
    quantidade = _as_float(quantidade)
    if quantidade <= 0:
        raise HTTPException(status_code=422, detail="Quantidade de consumo deve ser maior que zero.")
    key = f"consumo:{apontamento_id}:{saldo_lote_id}:{material_key}"
    existing = await database.estoque_movimentos_lote.find_one(
        {"tenant_id": tenant_id, "idempotency_key": key}, {"_id": 0}
    )
    if existing:
        return existing

    physical_expr = {"$ifNull": ["$quantidade", {"$ifNull": ["$quantidade_atual", 0]}]}
    reserved_expr = {"$ifNull": ["$quantidade_reservada", 0]}
    updated = await database.estoque_saldos_lote.find_one_and_update(
        {
            "id": saldo_lote_id,
            "tenant_id": tenant_id,
            "$expr": {"$and": [
                {"$gte": [physical_expr, quantidade]},
                {"$gte": [reserved_expr, quantidade]},
            ]},
        },
        {
            "$inc": {
                "quantidade": -quantidade,
                "quantidade_atual": -quantidade,
                "quantidade_reservada": -quantidade,
            },
            "$set": {"updated_at": now_iso_fn()},
        },
        return_document=ReturnDocument.AFTER,
        projection={"_id": 0},
    )
    if not updated:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "empenho_insuficiente_para_consumo",
                "message": "O lote nao possui saldo fisico/empenhado suficiente para o apontamento.",
                "saldo_lote_id": saldo_lote_id,
                "quantidade": quantidade,
            },
        )

    physical_after = saldo_quantidade_fisica(updated)
    reserved_after = saldo_quantidade_reservada(updated)
    aggregate_changed = False
    if hasattr(database, "estoque_items") and updated.get("item_id"):
        aggregate = await database.estoque_items.find_one_and_update(
            {
                "id": updated["item_id"],
                "tenant_id": tenant_id,
                "quantidade_atual": {"$gte": quantidade},
            },
            {"$inc": {"quantidade_atual": -quantidade}, "$set": {"updated_at": now_iso_fn()}},
            return_document=ReturnDocument.AFTER,
            projection={"_id": 0},
        )
        if not aggregate:
            await database.estoque_saldos_lote.update_one(
                {"id": saldo_lote_id, "tenant_id": tenant_id},
                {"$inc": {
                    "quantidade": quantidade,
                    "quantidade_atual": quantidade,
                    "quantidade_reservada": quantidade,
                }, "$set": {"updated_at": now_iso_fn()}},
            )
            raise HTTPException(status_code=409, detail="Saldo agregado insuficiente ou item de estoque ausente.")
        aggregate_changed = True
    await database.estoque_saldos_lote.update_one(
        {"id": saldo_lote_id, "tenant_id": tenant_id},
        {"$set": {
            "status": "zerado" if physical_after <= 0.000001 else updated.get("status", "disponivel"),
            "reserva_status": "livre" if reserved_after <= 0.000001 else "reservado",
            "updated_at": now_iso_fn(),
        }},
    )
    try:
        return await append_lot_ledger_event(
            database,
            new_id_fn=new_id_fn,
            now_iso_fn=now_iso_fn,
            tenant_id=tenant_id,
            saldo=updated,
            natureza="movimento",
            evento="CONSUMO_OP",
            quantidade=quantidade,
            quantidade_delta=-quantidade,
            reserva_delta=-quantidade,
            quantidade_antes=physical_after + quantidade,
            quantidade_depois=physical_after,
            motivo=f"Consumo no apontamento {apontamento_id} da OP {op_id}",
            referencia=apontamento_id,
            op_id=op_id,
            wms_separacao_id=wms_separacao_id,
            usuario=usuario,
            idempotency_key=key,
            metadata={"material_key": material_key, "op_item_idx": op_item_idx},
        )
    except DuplicateKeyError:
        await database.estoque_saldos_lote.update_one(
            {"id": saldo_lote_id, "tenant_id": tenant_id},
            {"$inc": {
                "quantidade": quantidade,
                "quantidade_atual": quantidade,
                "quantidade_reservada": quantidade,
            }, "$set": {"updated_at": now_iso_fn()}},
        )
        if aggregate_changed:
            await database.estoque_items.update_one(
                {"id": updated.get("item_id"), "tenant_id": tenant_id},
                {"$inc": {"quantidade_atual": quantidade}, "$set": {"updated_at": now_iso_fn()}},
            )
        return await database.estoque_movimentos_lote.find_one(
            {"tenant_id": tenant_id, "idempotency_key": key}, {"_id": 0}
        )


async def estornar_consumo_saldo_lote(
    database,
    *,
    new_id_fn,
    now_iso_fn,
    tenant_id: str,
    saldo_lote_id: str,
    quantidade: float,
    op_id: str,
    wms_separacao_id: str,
    apontamento_id: str,
    usuario: Dict[str, Any],
    motivo: str,
    material_key: str = "",
    op_item_idx: int = 0,
) -> Dict[str, Any]:
    quantidade = _as_float(quantidade)
    key = f"estorno-consumo:{apontamento_id}:{saldo_lote_id}:{material_key}"
    existing = await database.estoque_movimentos_lote.find_one(
        {"tenant_id": tenant_id, "idempotency_key": key}, {"_id": 0}
    )
    if existing:
        return existing
    before = await database.estoque_saldos_lote.find_one(
        {"id": saldo_lote_id, "tenant_id": tenant_id}, {"_id": 0}
    )
    await database.estoque_saldos_lote.update_one(
        {"id": saldo_lote_id, "tenant_id": tenant_id},
        {"$inc": {
            "quantidade": quantidade,
            "quantidade_atual": quantidade,
            "quantidade_reservada": quantidade,
        }, "$set": {"status": "disponivel", "reserva_status": "reservado", "updated_at": now_iso_fn()}},
    )
    if hasattr(database, "estoque_items") and (before or {}).get("item_id"):
        await database.estoque_items.update_one(
            {"id": before.get("item_id"), "tenant_id": tenant_id},
            {"$inc": {"quantidade_atual": quantidade}, "$set": {"updated_at": now_iso_fn()}},
        )
    updated = await database.estoque_saldos_lote.find_one(
        {"id": saldo_lote_id, "tenant_id": tenant_id}, {"_id": 0}
    )
    return await append_lot_ledger_event(
        database,
        new_id_fn=new_id_fn,
        now_iso_fn=now_iso_fn,
        tenant_id=tenant_id,
        saldo=updated,
        natureza="movimento",
        evento="ESTORNO_CONSUMO_OP",
        quantidade=quantidade,
        quantidade_delta=quantidade,
        reserva_delta=quantidade,
        quantidade_antes=saldo_quantidade_fisica(before or {}),
        quantidade_depois=saldo_quantidade_fisica(updated or {}),
        motivo=motivo,
        referencia=apontamento_id,
        op_id=op_id,
        wms_separacao_id=wms_separacao_id,
        usuario=usuario,
        idempotency_key=key,
        metadata={"material_key": material_key, "op_item_idx": op_item_idx},
    )


async def baixar_saldo_lote_expedicao(
    database,
    *,
    new_id_fn,
    now_iso_fn,
    tenant_id: str,
    saldo_lote_id: str,
    quantidade: float,
    expedicao_id: str,
    item_index: int,
    idempotency_key: str,
    usuario: Dict[str, Any],
) -> Dict[str, Any]:
    quantidade = _as_float(quantidade)
    key = f"expedicao:{idempotency_key}:{saldo_lote_id}:{item_index}"
    existing = await database.estoque_movimentos_lote.find_one(
        {"tenant_id": tenant_id, "idempotency_key": key}, {"_id": 0}
    )
    if existing:
        return existing

    physical_expr = {"$ifNull": ["$quantidade", {"$ifNull": ["$quantidade_atual", 0]}]}
    updated = await database.estoque_saldos_lote.find_one_and_update(
        {
            "id": saldo_lote_id,
            "tenant_id": tenant_id,
            "$expr": {"$gte": [physical_expr, quantidade]},
        },
        {
            "$inc": {"quantidade": -quantidade, "quantidade_atual": -quantidade},
            "$set": {"updated_at": now_iso_fn()},
        },
        return_document=ReturnDocument.AFTER,
        projection={"_id": 0},
    )
    if not updated:
        raise HTTPException(status_code=409, detail={
            "error": "saldo_lote_insuficiente_expedicao",
            "message": "Saldo insuficiente no lote selecionado para expedicao.",
            "saldo_lote_id": saldo_lote_id,
            "quantidade": quantidade,
        })

    aggregate_changed = False
    if hasattr(database, "estoque_items") and updated.get("item_id"):
        aggregate = await database.estoque_items.find_one_and_update(
            {"id": updated["item_id"], "tenant_id": tenant_id, "quantidade_atual": {"$gte": quantidade}},
            {"$inc": {"quantidade_atual": -quantidade}, "$set": {"updated_at": now_iso_fn()}},
            return_document=ReturnDocument.AFTER,
            projection={"_id": 0},
        )
        if not aggregate:
            await database.estoque_saldos_lote.update_one(
                {"id": saldo_lote_id, "tenant_id": tenant_id},
                {"$inc": {"quantidade": quantidade, "quantidade_atual": quantidade}, "$set": {"updated_at": now_iso_fn()}},
            )
            raise HTTPException(status_code=409, detail="Saldo agregado insuficiente para expedicao.")
        aggregate_changed = True

    physical_after = saldo_quantidade_fisica(updated)
    await database.estoque_saldos_lote.update_one(
        {"id": saldo_lote_id, "tenant_id": tenant_id},
        {"$set": {"status": "zerado" if physical_after <= 0.000001 else updated.get("status", "disponivel"), "updated_at": now_iso_fn()}},
    )
    try:
        return await append_lot_ledger_event(
            database,
            new_id_fn=new_id_fn,
            now_iso_fn=now_iso_fn,
            tenant_id=tenant_id,
            saldo=updated,
            natureza="movimento",
            evento="SAIDA_EXPEDICAO",
            quantidade=quantidade,
            quantidade_delta=-quantidade,
            quantidade_antes=physical_after + quantidade,
            quantidade_depois=physical_after,
            motivo=f"Saida da expedicao {expedicao_id}",
            documento=expedicao_id,
            referencia=expedicao_id,
            usuario=usuario,
            idempotency_key=key,
            metadata={"expedicao_id": expedicao_id, "item_index": item_index},
        )
    except DuplicateKeyError:
        await database.estoque_saldos_lote.update_one(
            {"id": saldo_lote_id, "tenant_id": tenant_id},
            {"$inc": {"quantidade": quantidade, "quantidade_atual": quantidade}, "$set": {"updated_at": now_iso_fn()}},
        )
        if aggregate_changed:
            await database.estoque_items.update_one(
                {"id": updated.get("item_id"), "tenant_id": tenant_id},
                {"$inc": {"quantidade_atual": quantidade}, "$set": {"updated_at": now_iso_fn()}},
            )
        return await database.estoque_movimentos_lote.find_one(
            {"tenant_id": tenant_id, "idempotency_key": key}, {"_id": 0}
        )


async def estornar_saida_expedicao(
    database,
    *,
    new_id_fn,
    now_iso_fn,
    tenant_id: str,
    saldo_lote_id: str,
    quantidade: float,
    expedicao_id: str,
    item_index: int,
    idempotency_key: str,
    usuario: Dict[str, Any],
    motivo: str,
) -> Dict[str, Any]:
    quantidade = _as_float(quantidade)
    key = f"estorno-expedicao:{idempotency_key}:{saldo_lote_id}:{item_index}"
    existing = await database.estoque_movimentos_lote.find_one(
        {"tenant_id": tenant_id, "idempotency_key": key}, {"_id": 0}
    )
    if existing:
        return existing
    before = await database.estoque_saldos_lote.find_one(
        {"id": saldo_lote_id, "tenant_id": tenant_id}, {"_id": 0}
    )
    if not before:
        raise HTTPException(status_code=404, detail="Saldo/lote nao encontrado para estorno da expedicao.")
    await database.estoque_saldos_lote.update_one(
        {"id": saldo_lote_id, "tenant_id": tenant_id},
        {"$inc": {"quantidade": quantidade, "quantidade_atual": quantidade}, "$set": {"status": "disponivel", "updated_at": now_iso_fn()}},
    )
    aggregate_changed = False
    if hasattr(database, "estoque_items") and before.get("item_id"):
        await database.estoque_items.update_one(
            {"id": before["item_id"], "tenant_id": tenant_id},
            {"$inc": {"quantidade_atual": quantidade}, "$set": {"updated_at": now_iso_fn()}},
        )
        aggregate_changed = True
    updated = await database.estoque_saldos_lote.find_one(
        {"id": saldo_lote_id, "tenant_id": tenant_id}, {"_id": 0}
    )
    try:
        return await append_lot_ledger_event(
            database,
            new_id_fn=new_id_fn,
            now_iso_fn=now_iso_fn,
            tenant_id=tenant_id,
            saldo=updated,
            natureza="movimento",
            evento="ESTORNO_SAIDA_EXPEDICAO",
            quantidade=quantidade,
            quantidade_delta=quantidade,
            quantidade_antes=saldo_quantidade_fisica(before),
            quantidade_depois=saldo_quantidade_fisica(updated or {}),
            motivo=motivo,
            documento=expedicao_id,
            referencia=expedicao_id,
            usuario=usuario,
            idempotency_key=key,
            metadata={"expedicao_id": expedicao_id, "item_index": item_index},
        )
    except Exception as exc:
        await database.estoque_saldos_lote.update_one(
            {"id": saldo_lote_id, "tenant_id": tenant_id},
            {"$inc": {"quantidade": -quantidade, "quantidade_atual": -quantidade},
             "$set": {"status": before.get("status", "zerado"), "updated_at": now_iso_fn()}},
        )
        if aggregate_changed:
            await database.estoque_items.update_one(
                {"id": before.get("item_id"), "tenant_id": tenant_id},
                {"$inc": {"quantidade_atual": -quantidade}, "$set": {"updated_at": now_iso_fn()}},
            )
        if isinstance(exc, DuplicateKeyError):
            return await database.estoque_movimentos_lote.find_one(
                {"tenant_id": tenant_id, "idempotency_key": key}, {"_id": 0}
            )
        raise
