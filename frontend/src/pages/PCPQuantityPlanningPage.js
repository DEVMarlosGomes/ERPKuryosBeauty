import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import api, { formatApiError } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import {
  ArrowLeft,
  ClipboardList,
  Factory,
  Layers3,
  Loader2,
  PackageCheck,
  Plus,
  RefreshCw,
  Search,
  ShieldAlert,
} from "lucide-react";

const PLANNABLE_ORDER_STATUSES = new Set(["confirmado", "em_producao"]);
const ACTIVE_ALLOCATION_STATUSES = new Set(["planejado", "parcial", "coberto"]);

function numberBR(value) {
  return Number(value || 0).toLocaleString("pt-BR", { maximumFractionDigits: 2 });
}

function normalizeSearch(value) {
  return String(value || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
}

function getClientName(order) {
  return order?.cliente?.nome || order?.cliente?.razao_social || order?.cliente_nome || "-";
}

function getOrderQuantity(order) {
  return (order.items || []).reduce((sum, item) => sum + Number(item.qtd || item.qtd_planejada || 0), 0);
}

function getItemQuantity(item) {
  return Number(item?.qtd || item?.qtd_planejada || 0);
}

function statusLabel(status) {
  return String(status || "sem_status").replaceAll("_", " ");
}

function allocationStatusClass(status) {
  if (status === "coberto") return "bg-emerald-500/10 text-emerald-700 border-emerald-300 dark:text-emerald-300";
  if (status === "parcial") return "bg-amber-500/10 text-amber-700 border-amber-300 dark:text-amber-300";
  if (status === "cancelado") return "bg-red-500/10 text-red-700 border-red-300 dark:text-red-300";
  return "bg-blue-500/10 text-blue-700 border-blue-300 dark:text-blue-300";
}

function getErrorMessage(err) {
  const detail = err?.response?.data?.detail ?? err;
  if (detail && typeof detail === "object" && detail.message) return detail.message;
  return formatApiError(detail);
}

function buildDateTimeLocal(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 16);
  const offset = date.getTimezoneOffset();
  return new Date(date.getTime() - offset * 60000).toISOString().slice(0, 16);
}

function toApiDateTime(value) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toISOString();
}

export default function PCPQuantityPlanningPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [orders, setOrders] = useState([]);
  const [selectedOrder, setSelectedOrder] = useState(null);
  const [allocations, setAllocations] = useState([]);
  const [lines, setLines] = useState([]);
  const [loading, setLoading] = useState(true);
  const [orderLoading, setOrderLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [showClosed, setShowClosed] = useState(false);
  const [featureBlocked, setFeatureBlocked] = useState("");
  const [allocationTarget, setAllocationTarget] = useState(null);
  const [opTarget, setOpTarget] = useState(null);
  const selectedOrderId = searchParams.get("order_id") || "";

  const loadBase = useCallback(async () => {
    setLoading(true);
    try {
      const [ordersRes, linesRes] = await Promise.all([
        api.get("/orders"),
        api.get("/pcp/linhas").catch(() => ({ data: [] })),
      ]);
      const nextOrders = ordersRes.data || [];
      setOrders(nextOrders);
      setLines(linesRes.data || []);
      if (!selectedOrderId && nextOrders.length) {
        const first = nextOrders.find((order) => PLANNABLE_ORDER_STATUSES.has(order.status)) || nextOrders[0];
        setSearchParams({ order_id: first.id }, { replace: true });
      }
    } catch (err) {
      toast.error(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [selectedOrderId, setSearchParams]);

  const loadSelectedOrder = useCallback(async (orderId) => {
    if (!orderId) {
      setSelectedOrder(null);
      setAllocations([]);
      return;
    }
    setOrderLoading(true);
    setFeatureBlocked("");
    try {
      await api.get(`/orders/${orderId}/pcp-allocations`);
      const [orderRes, allocationsRes] = await Promise.all([
        api.get(`/orders/${orderId}`),
        api.get(`/orders/${orderId}/pcp-allocations`),
      ]);
      setSelectedOrder(orderRes.data);
      setAllocations(allocationsRes.data || []);
    } catch (err) {
      if (err?.response?.status === 403) {
        setFeatureBlocked(getErrorMessage(err));
        const fallback = orders.find((order) => order.id === orderId) || null;
        setSelectedOrder(fallback);
        setAllocations([]);
      } else {
        toast.error(getErrorMessage(err));
      }
    } finally {
      setOrderLoading(false);
    }
  }, [orders]);

  useEffect(() => { loadBase(); }, [loadBase]);
  useEffect(() => { loadSelectedOrder(selectedOrderId); }, [loadSelectedOrder, selectedOrderId]);

  const activeLines = useMemo(() => lines.filter((line) => line.status !== "inativa"), [lines]);
  const lineMap = useMemo(() => new Map(lines.map((line) => [line.id, line.nome || line.id])), [lines]);

  const filteredOrders = useMemo(() => {
    const q = normalizeSearch(search);
    return orders
      .filter((order) => showClosed || !["concluido", "cancelado"].includes(order.status))
      .filter((order) => {
        if (!q) return true;
        const hay = normalizeSearch([
          order.numero_pedido,
          getClientName(order),
          order.project_name,
          ...(order.items || []).map((item) => `${item.item || ""} ${item.codigo_kuryos || ""}`),
        ].join(" "));
        return hay.includes(q);
      })
      .sort((a, b) => {
        const aReady = PLANNABLE_ORDER_STATUSES.has(a.status) ? 0 : 1;
        const bReady = PLANNABLE_ORDER_STATUSES.has(b.status) ? 0 : 1;
        return aReady - bReady || String(b.created_at || "").localeCompare(String(a.created_at || ""));
      });
  }, [orders, search, showClosed]);

  const allocationsByItem = useMemo(() => {
    const map = new Map();
    for (const allocation of allocations) {
      const key = allocation.sales_order_item_id;
      if (!key) continue;
      const list = map.get(key) || [];
      list.push(allocation);
      map.set(key, list);
    }
    return map;
  }, [allocations]);

  const totals = useMemo(() => {
    const items = selectedOrder?.items || [];
    const orderQty = items.reduce((sum, item) => sum + getItemQuantity(item), 0);
    const allocatedQty = allocations
      .filter((allocation) => ACTIVE_ALLOCATION_STATUSES.has(allocation.status))
      .reduce((sum, allocation) => sum + Number(allocation.planned_quantity || 0), 0);
    const opQty = allocations.reduce((sum, allocation) => sum + Number(allocation.consumed_quantity || 0), 0);
    return { orderQty, allocatedQty, opQty, remainingQty: Math.max(orderQty - allocatedQty, 0) };
  }, [selectedOrder, allocations]);

  const selectOrder = (orderId) => {
    setSearchParams({ order_id: orderId });
  };

  const refreshSelected = async () => {
    await loadSelectedOrder(selectedOrderId);
  };

  const openAllocationDialog = (item) => {
    const itemAllocations = allocationsByItem.get(item.id) || [];
    const allocated = itemAllocations
      .filter((allocation) => ACTIVE_ALLOCATION_STATUSES.has(allocation.status))
      .reduce((sum, allocation) => sum + Number(allocation.planned_quantity || 0), 0);
    const remaining = Math.max(getItemQuantity(item) - allocated, 0);
    setAllocationTarget({
      item,
      remaining,
      form: {
        planned_quantity: remaining || "",
        line_id: "none",
        planned_start: "",
        planned_end: "",
        priority: 0,
        notes: "",
        override_excess: false,
        override_reason: "",
      },
      saving: false,
    });
  };

  const updateAllocationForm = (field, value) => {
    setAllocationTarget((target) => target ? {
      ...target,
      form: { ...target.form, [field]: value },
    } : target);
  };

  const saveAllocation = async () => {
    if (!selectedOrder || !allocationTarget?.item?.id) return;
    const form = allocationTarget.form;
    setAllocationTarget((target) => ({ ...target, saving: true }));
    try {
      await api.post(`/orders/${selectedOrder.id}/items/${allocationTarget.item.id}/pcp-allocations`, {
        planned_quantity: Number(form.planned_quantity || 0),
        line_id: form.line_id === "none" ? null : form.line_id,
        planned_start: toApiDateTime(form.planned_start),
        planned_end: toApiDateTime(form.planned_end),
        priority: Number(form.priority || 0),
        notes: form.notes || "",
        override_excess: !!form.override_excess,
        override_reason: form.override_reason || null,
      });
      toast.success("Quantidade planejada registrada.");
      setAllocationTarget(null);
      await refreshSelected();
    } catch (err) {
      toast.error(getErrorMessage(err));
    } finally {
      setAllocationTarget((target) => target ? { ...target, saving: false } : target);
    }
  };

  const openOpDialog = (allocation) => {
    const remaining = Number(allocation.remaining_quantity ?? allocation.planned_quantity ?? 0);
    setOpTarget({
      allocation,
      form: {
        quantity: remaining || "",
        observacoes: "",
        override_excess: false,
        override_reason: "",
      },
      saving: false,
    });
  };

  const updateOpForm = (field, value) => {
    setOpTarget((target) => target ? {
      ...target,
      form: { ...target.form, [field]: value },
    } : target);
  };

  const createOp = async () => {
    if (!selectedOrder || !opTarget?.allocation?.id) return;
    const form = opTarget.form;
    setOpTarget((target) => ({ ...target, saving: true }));
    try {
      const res = await api.post(`/orders/${selectedOrder.id}/pcp-allocations/${opTarget.allocation.id}/create-op`, {
        quantity: Number(form.quantity || 0),
        observacoes: form.observacoes || "",
        override_excess: !!form.override_excess,
        override_reason: form.override_reason || null,
      });
      toast.success(`OP ${res.data?.numero_op || ""} criada.`);
      setOpTarget(null);
      await refreshSelected();
    } catch (err) {
      toast.error(getErrorMessage(err));
    } finally {
      setOpTarget((target) => target ? { ...target, saving: false } : target);
    }
  };

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center bg-background">
        <Loader2 className="h-7 w-7 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="h-full overflow-auto bg-background">
      <div className="mx-auto max-w-[1500px] space-y-5 p-4 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <Button variant="ghost" className="mb-2 gap-1 px-0 text-muted-foreground" onClick={() => navigate("/pcp/planejamento")}>
              <ArrowLeft className="h-4 w-4" /> Planejamento
            </Button>
            <h1 className="flex items-center gap-2 text-2xl font-heading font-semibold tracking-tight">
              <Layers3 className="h-6 w-6" />
              Quantidades
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Pedido, item, saldo planejado e OPs emitidas por alocacao.
            </p>
          </div>
          <Button variant="outline" onClick={loadBase} className="gap-1.5">
            <RefreshCw className="h-4 w-4" /> Atualizar
          </Button>
        </div>

        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatCard label="Pedidos" value={filteredOrders.length} icon={ClipboardList} />
          <StatCard label="Qtd pedido" value={numberBR(totals.orderQty)} icon={PackageCheck} />
          <StatCard label="Planejado" value={numberBR(totals.allocatedQty)} icon={Layers3} />
          <StatCard label="Em OPs" value={numberBR(totals.opQty)} icon={Factory} />
        </div>

        <div className="grid gap-5 xl:grid-cols-[380px_minmax(0,1fr)]">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Pedidos</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Buscar pedido, cliente, SKU..." className="pl-9" />
              </div>
              <label className="flex min-h-9 cursor-pointer items-center gap-2 rounded-md text-sm text-muted-foreground">
                <input
                  type="checkbox"
                  checked={showClosed}
                  onChange={(event) => setShowClosed(event.target.checked)}
                  className="h-4 w-4 accent-primary"
                />
                Mostrar concluidos/cancelados
              </label>
              <div className="max-h-[62vh] space-y-2 overflow-y-auto pr-1">
                {filteredOrders.map((order) => {
                  const active = order.id === selectedOrderId;
                  const plannable = PLANNABLE_ORDER_STATUSES.has(order.status);
                  return (
                    <button
                      key={order.id}
                      type="button"
                      onClick={() => selectOrder(order.id)}
                      className={`w-full rounded-md border p-3 text-left transition hover:bg-accent ${active ? "border-primary bg-primary/5" : "border-border bg-card"}`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="truncate font-mono text-xs font-bold text-primary">#{order.numero_pedido || order.id}</p>
                          <p className="truncate text-sm font-semibold">{getClientName(order)}</p>
                        </div>
                        <Badge variant="outline" className={plannable ? "border-blue-300 text-blue-700 dark:text-blue-300" : ""}>
                          {statusLabel(order.status)}
                        </Badge>
                      </div>
                      <p className="mt-2 truncate text-xs text-muted-foreground">
                        {(order.items || []).map((item) => item.item).filter(Boolean).join(" | ") || order.project_name || "Sem itens"}
                      </p>
                      <p className="mt-1 text-xs text-muted-foreground">{numberBR(getOrderQuantity(order))} un</p>
                    </button>
                  );
                })}
                {filteredOrders.length === 0 && (
                  <div className="rounded-md border border-dashed p-8 text-center text-sm text-muted-foreground">
                    Nenhum pedido encontrado.
                  </div>
                )}
              </div>
            </CardContent>
          </Card>

          <div className="space-y-4">
            {orderLoading ? (
              <Card>
                <CardContent className="flex items-center justify-center py-20">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </CardContent>
              </Card>
            ) : !selectedOrder ? (
              <EmptyState />
            ) : (
              <>
                {featureBlocked && (
                  <Card className="border-amber-300 bg-amber-50/70 dark:border-amber-900 dark:bg-amber-950/20">
                    <CardContent className="flex gap-3 p-4 text-sm">
                      <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-amber-700 dark:text-amber-300" />
                      <div>
                        <p className="font-semibold text-amber-900 dark:text-amber-100">pcp_quantity_planning_v2 inativa</p>
                        <p className="mt-1 text-amber-800 dark:text-amber-200">{featureBlocked}</p>
                      </div>
                    </CardContent>
                  </Card>
                )}

                <Card>
                  <CardContent className="p-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="font-mono text-sm font-bold text-primary">#{selectedOrder.numero_pedido || selectedOrder.id}</p>
                        <h2 className="truncate text-xl font-semibold">{getClientName(selectedOrder)}</h2>
                        <p className="mt-1 truncate text-sm text-muted-foreground">{selectedOrder.project_name || "Pedido comercial"}</p>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <Badge variant="outline">{statusLabel(selectedOrder.status)}</Badge>
                        <Badge variant="outline">{(selectedOrder.items || []).length} item(ns)</Badge>
                      </div>
                    </div>
                  </CardContent>
                </Card>

                <div className="space-y-3">
                  {(selectedOrder.items || []).map((item, index) => {
                    const itemId = item.id || "";
                    const itemAllocations = allocationsByItem.get(itemId) || [];
                    const allocated = itemAllocations
                      .filter((allocation) => ACTIVE_ALLOCATION_STATUSES.has(allocation.status))
                      .reduce((sum, allocation) => sum + Number(allocation.planned_quantity || 0), 0);
                    const consumed = itemAllocations.reduce((sum, allocation) => sum + Number(allocation.consumed_quantity || 0), 0);
                    const quantity = getItemQuantity(item);
                    const remaining = Math.max(quantity - allocated, 0);
                    const canAllocate = !featureBlocked && PLANNABLE_ORDER_STATUSES.has(selectedOrder.status) && !!itemId;

                    return (
                      <Card key={itemId || `${selectedOrder.id}-${index}`}>
                        <CardHeader className="pb-3">
                          <div className="flex flex-wrap items-start justify-between gap-3">
                            <div className="min-w-0">
                              <CardTitle className="truncate text-base">{item.item || `Item ${index + 1}`}</CardTitle>
                              <p className="mt-1 truncate text-xs text-muted-foreground">SKU: {item.codigo_kuryos || "A definir"}</p>
                            </div>
                            <Button size="sm" disabled={!canAllocate} onClick={() => openAllocationDialog(item)} className="gap-1.5">
                              <Plus className="h-4 w-4" /> Planejar
                            </Button>
                          </div>
                        </CardHeader>
                        <CardContent className="space-y-4">
                          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                            <MiniStat label="Pedido" value={numberBR(quantity)} />
                            <MiniStat label="Planejado" value={numberBR(allocated)} />
                            <MiniStat label="Saldo" value={numberBR(remaining)} />
                            <MiniStat label="OPs" value={numberBR(consumed)} />
                          </div>

                          <div className="overflow-x-auto">
                            <table className="w-full min-w-[860px] text-sm">
                              <thead>
                                <tr className="border-b bg-muted/40 text-left text-[11px] uppercase tracking-wide text-muted-foreground">
                                  <th className="p-3">Alocacao</th>
                                  <th className="p-3">Linha</th>
                                  <th className="p-3 text-right">Planejado</th>
                                  <th className="p-3 text-right">Em OPs</th>
                                  <th className="p-3 text-right">Saldo</th>
                                  <th className="p-3">Status</th>
                                  <th className="p-3 text-right">Acoes</th>
                                </tr>
                              </thead>
                              <tbody>
                                {itemAllocations.map((allocation) => (
                                  <tr key={allocation.id} className="border-b">
                                    <td className="p-3 align-top">
                                      <p className="font-mono text-xs font-bold text-primary">{allocation.id}</p>
                                      {allocation.notes && <p className="mt-1 max-w-[260px] truncate text-xs text-muted-foreground">{allocation.notes}</p>}
                                    </td>
                                    <td className="p-3 align-top">{lineMap.get(allocation.line_id) || allocation.line_id || "-"}</td>
                                    <td className="p-3 text-right align-top font-semibold">{numberBR(allocation.planned_quantity)}</td>
                                    <td className="p-3 text-right align-top">{numberBR(allocation.consumed_quantity)}</td>
                                    <td className="p-3 text-right align-top">{numberBR(allocation.remaining_quantity)}</td>
                                    <td className="p-3 align-top">
                                      <Badge className={allocationStatusClass(allocation.status)}>{statusLabel(allocation.status)}</Badge>
                                    </td>
                                    <td className="p-3 text-right align-top">
                                      <Button
                                        size="sm"
                                        variant="outline"
                                        disabled={featureBlocked || Number(allocation.remaining_quantity || 0) <= 0}
                                        onClick={() => openOpDialog(allocation)}
                                      >
                                        <Factory className="mr-1 h-3.5 w-3.5" /> OP
                                      </Button>
                                    </td>
                                  </tr>
                                ))}
                                {itemAllocations.length === 0 && (
                                  <tr>
                                    <td colSpan={7} className="p-6 text-center text-sm text-muted-foreground">
                                      Nenhuma quantidade planejada para este item.
                                    </td>
                                  </tr>
                                )}
                              </tbody>
                            </table>
                          </div>
                        </CardContent>
                      </Card>
                    );
                  })}
                  {(selectedOrder.items || []).length === 0 && <EmptyState />}
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      <Dialog open={!!allocationTarget} onOpenChange={(open) => !open && setAllocationTarget(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Planejar quantidade</DialogTitle>
          </DialogHeader>
          {allocationTarget && (
            <div className="space-y-4">
              <div className="rounded-md border bg-muted/40 p-3">
                <p className="font-semibold">{allocationTarget.item.item || "Item"}</p>
                <p className="mt-1 text-xs text-muted-foreground">Saldo disponivel: {numberBR(allocationTarget.remaining)} un</p>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                <Field label="Quantidade">
                  <Input
                    type="number"
                    min="0"
                    step="0.01"
                    value={allocationTarget.form.planned_quantity}
                    onChange={(event) => updateAllocationForm("planned_quantity", event.target.value)}
                  />
                </Field>
                <Field label="Linha">
                  <Select value={allocationTarget.form.line_id} onValueChange={(value) => updateAllocationForm("line_id", value)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none">Sem linha definida</SelectItem>
                      {activeLines.map((line) => <SelectItem key={line.id} value={line.id}>{line.nome || line.id}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </Field>
                <Field label="Inicio planejado">
                  <Input
                    type="datetime-local"
                    value={buildDateTimeLocal(allocationTarget.form.planned_start)}
                    onChange={(event) => updateAllocationForm("planned_start", event.target.value)}
                  />
                </Field>
                <Field label="Fim planejado">
                  <Input
                    type="datetime-local"
                    value={buildDateTimeLocal(allocationTarget.form.planned_end)}
                    onChange={(event) => updateAllocationForm("planned_end", event.target.value)}
                  />
                </Field>
                <Field label="Prioridade">
                  <Input
                    type="number"
                    min="0"
                    value={allocationTarget.form.priority}
                    onChange={(event) => updateAllocationForm("priority", event.target.value)}
                  />
                </Field>
                <label className="flex min-h-10 items-center gap-2 pt-6 text-sm text-muted-foreground">
                  <input
                    type="checkbox"
                    checked={allocationTarget.form.override_excess}
                    onChange={(event) => updateAllocationForm("override_excess", event.target.checked)}
                    className="h-4 w-4 accent-primary"
                  />
                  Permitir excesso
                </label>
              </div>
              <Field label="Observacoes">
                <Textarea
                  rows={3}
                  value={allocationTarget.form.notes}
                  onChange={(event) => updateAllocationForm("notes", event.target.value)}
                />
              </Field>
              {allocationTarget.form.override_excess && (
                <Field label="Motivo do excesso">
                  <Textarea
                    rows={2}
                    value={allocationTarget.form.override_reason}
                    onChange={(event) => updateAllocationForm("override_reason", event.target.value)}
                  />
                </Field>
              )}
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setAllocationTarget(null)}>Cancelar</Button>
            <Button disabled={allocationTarget?.saving} onClick={saveAllocation}>
              {allocationTarget?.saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Salvar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!opTarget} onOpenChange={(open) => !open && setOpTarget(null)}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>Gerar OP da alocacao</DialogTitle>
          </DialogHeader>
          {opTarget && (
            <div className="space-y-4">
              <div className="rounded-md border bg-muted/40 p-3">
                <p className="font-semibold">{opTarget.allocation.item_nome || opTarget.allocation.codigo_kuryos || "Alocacao"}</p>
                <p className="mt-1 text-xs text-muted-foreground">Saldo da alocacao: {numberBR(opTarget.allocation.remaining_quantity)} un</p>
              </div>
              <Field label="Quantidade da OP">
                <Input
                  type="number"
                  min="0"
                  step="0.01"
                  value={opTarget.form.quantity}
                  onChange={(event) => updateOpForm("quantity", event.target.value)}
                />
              </Field>
              <Field label="Observacoes">
                <Textarea
                  rows={3}
                  value={opTarget.form.observacoes}
                  onChange={(event) => updateOpForm("observacoes", event.target.value)}
                />
              </Field>
              <label className="flex min-h-10 items-center gap-2 text-sm text-muted-foreground">
                <input
                  type="checkbox"
                  checked={opTarget.form.override_excess}
                  onChange={(event) => updateOpForm("override_excess", event.target.checked)}
                  className="h-4 w-4 accent-primary"
                />
                Permitir excesso
              </label>
              {opTarget.form.override_excess && (
                <Field label="Motivo do excesso">
                  <Textarea
                    rows={2}
                    value={opTarget.form.override_reason}
                    onChange={(event) => updateOpForm("override_reason", event.target.value)}
                  />
                </Field>
              )}
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpTarget(null)}>Cancelar</Button>
            <Button disabled={opTarget?.saving} onClick={createOp}>
              {opTarget?.saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Factory className="mr-2 h-4 w-4" />}
              Gerar OP
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function StatCard({ label, value, icon: Icon }) {
  return (
    <Card>
      <CardContent className="p-3">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="truncate text-[11px] uppercase tracking-wider text-muted-foreground">{label}</div>
            <div className="mt-0.5 truncate text-2xl font-bold">{value}</div>
          </div>
          {Icon && <Icon className="h-5 w-5 shrink-0 text-primary opacity-70" />}
        </div>
      </CardContent>
    </Card>
  );
}

function MiniStat({ label, value }) {
  return (
    <div className="rounded-md border bg-muted/30 px-3 py-2">
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-1 truncate font-mono text-sm font-bold">{value}</p>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <div>
      <Label className="text-xs text-muted-foreground">{label}</Label>
      <div className="mt-1">{children}</div>
    </div>
  );
}

function EmptyState() {
  return (
    <Card className="border-dashed">
      <CardContent className="py-16 text-center">
        <Layers3 className="mx-auto mb-4 h-14 w-14 text-muted-foreground/30" />
        <h3 className="mb-1 text-lg font-semibold">Nenhum item selecionado</h3>
        <p className="mx-auto max-w-md text-sm text-muted-foreground">
          Selecione um pedido confirmado ou em producao para revisar saldos por item.
        </p>
      </CardContent>
    </Card>
  );
}
