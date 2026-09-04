import React, { useState, useEffect, useCallback, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { toast } from "sonner";
import {
  ArrowDown,
  ArrowRight,
  ArrowUp,
  Bell,
  Building2,
  CheckCircle2,
  ClipboardList,
  Clock3,
  DollarSign,
  Factory,
  FileText,
  GripVertical,
  Layers3,
  Loader2,
  PackageCheck,
  Paperclip,
  RefreshCw,
  Route,
  Search,
  ShoppingCart,
  SlidersHorizontal,
  Download,
} from "lucide-react";

const STATUS_CONFIG = {
  rascunho: { label: "Rascunho", color: "bg-slate-500/10 text-slate-600 border-slate-300 dark:text-slate-300" },
  confirmado: { label: "Confirmado", color: "bg-blue-500/10 text-blue-600 border-blue-300 dark:text-blue-300" },
  em_producao: { label: "Em Producao", color: "bg-amber-500/10 text-amber-700 border-amber-300 dark:text-amber-300" },
  concluido: { label: "Concluido", color: "bg-green-500/10 text-green-700 border-green-300 dark:text-green-300" },
  cancelado: { label: "Cancelado", color: "bg-red-500/10 text-red-700 border-red-300 dark:text-red-300" },
};

const OP_STATUS_CONFIG = {
  aberta: { label: "OP aberta", color: "bg-blue-500/10 text-blue-700 border-blue-300 dark:text-blue-300" },
  em_processo: { label: "Em processo", color: "bg-amber-500/10 text-amber-700 border-amber-300 dark:text-amber-300" },
  pausada: { label: "Pausada", color: "bg-orange-500/10 text-orange-700 border-orange-300 dark:text-orange-300" },
  aguardando_confirmacao_pcp: { label: "Aguard. PCP", color: "bg-indigo-500/10 text-indigo-700 border-indigo-300 dark:text-indigo-300" },
  concluida: { label: "OP concluida", color: "bg-green-500/10 text-green-700 border-green-300 dark:text-green-300" },
  cancelada: { label: "Cancelada", color: "bg-red-500/10 text-red-700 border-red-300 dark:text-red-300" },
};

const PCP_STATUS_CONFIG = {
  planejado: { label: "Planejado", color: "bg-blue-500/10 text-blue-700 border-blue-300 dark:text-blue-300" },
  em_execucao: { label: "Em execucao", color: "bg-amber-500/10 text-amber-700 border-amber-300 dark:text-amber-300" },
  bloqueado: { label: "Bloqueado", color: "bg-red-500/10 text-red-700 border-red-300 dark:text-red-300" },
  concluido: { label: "Concluido PCP", color: "bg-green-500/10 text-green-700 border-green-300 dark:text-green-300" },
};

const FOLLOWUP_LABELS = { "1m": "1 mes", "3m": "3 meses", "6m": "6 meses" };

function formatCurrencyBR(value) {
  if (!value && value !== 0) return "R$ 0,00";
  return `R$ ${Number(value).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatDateBR(iso) {
  if (!iso) return "-";
  try {
    return new Date(iso).toLocaleDateString("pt-BR");
  } catch {
    return iso;
  }
}

function numberBR(value) {
  return Number(value || 0).toLocaleString("pt-BR", { maximumFractionDigits: 0 });
}

function pct(done, total) {
  const t = Number(total || 0);
  if (t <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round((Number(done || 0) / t) * 100)));
}

function daysOpen(iso) {
  if (!iso) return 0;
  const created = new Date(iso);
  if (Number.isNaN(created.getTime())) return 0;
  const diff = Date.now() - created.getTime();
  return Math.max(0, Math.floor(diff / 86400000));
}

function getClientName(order) {
  return order?.cliente?.nome || order?.cliente?.razao_social || order?.cliente_nome || "-";
}

function getOrderTotalQty(order) {
  return (order.items || []).reduce((sum, item) => sum + Number(item.qtd || item.qtd_planejada || 0), 0);
}

function getOpProducedQty(op) {
  return (op?.items || []).reduce((sum, item) => sum + Number(item.qtd_produzida || 0), 0);
}

function normalizeSearch(value) {
  return String(value || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
}

function orderMatchesStatus(order, statusFilter) {
  if (statusFilter === "all") return true;
  if (statusFilter === "andamento") return !["concluido", "cancelado"].includes(order.status);
  return order.status === statusFilter;
}

function getOrderFollowupState(order) {
  const now = new Date();
  const fus = order.followups || [];
  if (!fus.length) return null;
  const pending = fus.filter(fu => !fu.notificado);
  if (!pending.length) return { label: "Todos notificados", color: "bg-green-100 text-green-700", marco: null };
  const next = pending.reduce((a, b) => new Date(a.vence_em) <= new Date(b.vence_em) ? a : b);
  const overdue = new Date(next.vence_em) < now;
  return {
    label: `Follow-up ${FOLLOWUP_LABELS[next.marco] || next.marco}${overdue ? " vencido" : ""}`,
    color: overdue ? "bg-red-100 text-red-700" : "bg-amber-100 text-amber-700",
    marco: next.marco,
    overdue,
  };
}

export default function OrdersPage() {
  const navigate = useNavigate();
  const [orders, setOrders] = useState([]);
  const [ops, setOps] = useState([]);
  const [pcpSlots, setPcpSlots] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("andamento");
  const [followupFilter, setFollowupFilter] = useState("all");
  const [lineFilter, setLineFilter] = useState("all");
  const [groupBy, setGroupBy] = useState("none");
  const [tab, setTab] = useState("producao");
  const [generatedStatus, setGeneratedStatus] = useState(null);
  const [priorityDraft, setPriorityDraft] = useState([]);
  const [savingPriority, setSavingPriority] = useState(false);
  const [creatingOpId, setCreatingOpId] = useState("");

  const fetchOrders = useCallback(async () => {
    setLoading(true);
    try {
      const params = {};
      if (search.trim()) params.q = search.trim();
      const [ordersRes, opsRes, slotsRes, generatorRes] = await Promise.all([
        api.get("/orders", { params }),
        api.get("/ops").catch(() => ({ data: [] })),
        api.get("/pcp/programacao").catch(() => ({ data: [] })),
        api.get("/orders/generated/status").catch(() => ({ data: null })),
      ]);
      setOrders(ordersRes.data || []);
      setOps(opsRes.data || []);
      setPcpSlots(slotsRes.data || []);
      setGeneratedStatus(generatorRes.data);
    } catch (err) {
      toast.error("Erro ao carregar pedidos");
    } finally {
      setLoading(false);
    }
  }, [search]);

  useEffect(() => { fetchOrders(); }, [fetchOrders]);

  const maps = useMemo(() => {
    const opsByOrderId = new Map();
    const slotsByOpId = new Map();
    for (const op of ops) {
      if (!op?.pedido_id) continue;
      const list = opsByOrderId.get(op.pedido_id) || [];
      list.push(op);
      opsByOrderId.set(op.pedido_id, list);
    }
    for (const slot of pcpSlots) {
      if (!slot?.op_id) continue;
      const list = slotsByOpId.get(slot.op_id) || [];
      list.push(slot);
      slotsByOpId.set(slot.op_id, list);
    }
    return { opsByOrderId, slotsByOpId };
  }, [ops, pcpSlots]);

  const filteredOrders = useMemo(() => {
    const q = normalizeSearch(search);
    return orders.filter(order => {
      if (!orderMatchesStatus(order, statusFilter)) return false;
      if (followupFilter !== "all") {
        const fus = order.followups || [];
        if (followupFilter === "pendente" && !fus.some(fu => !fu.notificado)) return false;
        if (followupFilter !== "pendente" && !fus.some(fu => fu.marco === followupFilter && !fu.notificado)) return false;
      }
      if (!q) return true;
      const text = normalizeSearch([
        order.numero_pedido,
        order.project_name,
        getClientName(order),
        order.cliente?.razao_social,
        ...(order.items || []).map(item => `${item.item} ${item.codigo_kuryos} ${item.codigo_cliente}`),
      ].join(" "));
      return text.includes(q);
    });
  }, [orders, search, statusFilter, followupFilter]);

  const productionRows = useMemo(() => {
    const rows = [];
    for (const order of filteredOrders) {
      const linkedOps = maps.opsByOrderId.get(order.id) || [];
      if (linkedOps.length) {
        for (const op of linkedOps) {
          const slots = maps.slotsByOpId.get(op.id) || [];
          const slot = slots[0] || null;
          const items = op.items?.length ? op.items : order.items || [];
          items.forEach((item, itemIndex) => {
            const total = Number(item.qtd_planejada || item.qtd || 0);
            const produzido = Number(item.qtd_produzida || slot?.qtd_produzida || 0);
            rows.push({
              id: `${order.id}-${op.id}-${itemIndex}`,
              order,
              op,
              slot,
              item,
              cliente: getClientName(order),
              produto: item.item || op.project_name || order.project_name || "Item sem descricao",
              sku: item.codigo_kuryos || slot?.sku || "A definir",
              qtdTotal: total,
              qtdProduzida: produzido,
              progress: pct(produzido, total),
              linha: op.linha_nome || slot?.linha_nome || "Sem linha",
              dataProducao: slot?.data || slot?.data_inicio || null,
              prioridade: Number(order.prioridade_pcp || 9999),
              openedDays: daysOpen(order.created_at || order.data_pedido),
            });
          });
        }
      } else {
        const items = order.items?.length ? order.items : [{ item: order.project_name || "Pedido sem item", qtd: 0, codigo_kuryos: "A definir" }];
        items.forEach((item, itemIndex) => {
          const total = Number(item.qtd || 0);
          rows.push({
            id: `${order.id}-sem-op-${itemIndex}`,
            order,
            op: null,
            slot: null,
            item,
            cliente: getClientName(order),
            produto: item.item || order.project_name || "Item sem descricao",
            sku: item.codigo_kuryos || "A definir",
            qtdTotal: total,
            qtdProduzida: 0,
            progress: 0,
            linha: "Sem linha",
            dataProducao: null,
            prioridade: Number(order.prioridade_pcp || 9999),
            openedDays: daysOpen(order.created_at || order.data_pedido),
          });
        });
      }
    }

    return rows
      .filter(row => lineFilter === "all" || row.linha === lineFilter)
      .sort((a, b) => (a.prioridade - b.prioridade) || b.openedDays - a.openedDays || String(a.produto).localeCompare(String(b.produto)));
  }, [filteredOrders, maps, lineFilter]);

  const commercialRows = useMemo(() => {
    return filteredOrders.map(order => {
      const linkedOps = maps.opsByOrderId.get(order.id) || [];
      const total = getOrderTotalQty(order);
      const produzido = linkedOps.reduce((sum, op) => {
        const slots = maps.slotsByOpId.get(op.id) || [];
        const bySlot = slots.reduce((s, slot) => s + Number(slot.qtd_produzida || 0), 0);
        return sum + Math.max(getOpProducedQty(op), bySlot);
      }, 0);
      const firstOp = linkedOps[0] || null;
      const firstSlot = firstOp ? (maps.slotsByOpId.get(firstOp.id) || [])[0] : null;
      return {
        id: order.id,
        order,
        ops: linkedOps,
        slot: firstSlot || null,
        cliente: getClientName(order),
        qtdTotal: total,
        qtdProduzida: produzido,
        progress: pct(produzido, total),
        openedDays: daysOpen(order.created_at || order.data_pedido),
        prioridade: Number(order.prioridade_pcp || 9999),
      };
    }).sort((a, b) => (a.prioridade - b.prioridade) || b.openedDays - a.openedDays);
  }, [filteredOrders, maps]);

  const lineOptions = useMemo(() => {
    const values = new Set(["Linha 1", "Linha 2", "Linha 3"]);
    for (const row of productionRows) values.add(row.linha || "Sem linha");
    return Array.from(values);
  }, [productionRows]);

  const counts = useMemo(() => {
    const active = commercialRows.filter(row => !["concluido", "cancelado"].includes(row.order.status));
    return {
      total: orders.length,
      andamento: active.length,
      semOp: commercialRows.filter(row => !row.ops.length).length,
      semPcp: commercialRows.filter(row => row.ops.length && !row.slot).length,
      concluido: orders.filter(o => o.status === "concluido").length,
      valor_total: orders.reduce((s, o) => s + (o.total_pedido || 0), 0),
    };
  }, [orders, commercialRows]);

  const priorityBaseRows = useMemo(() => {
    return commercialRows.filter(row => !["concluido", "cancelado"].includes(row.order.status));
  }, [commercialRows]);

  const prioritySignature = priorityBaseRows.map(row => `${row.id}:${row.prioridade}`).join("|");

  useEffect(() => {
    setPriorityDraft(priorityBaseRows.map(row => row.id));
  }, [prioritySignature, priorityBaseRows]);

  const priorityRowsById = useMemo(() => {
    return new Map(priorityBaseRows.map(row => [row.id, row]));
  }, [priorityBaseRows]);

  const persistPriority = async (ids) => {
    setSavingPriority(true);
    try {
      await Promise.all(ids.map((orderId, index) => api.put(`/orders/${orderId}`, { prioridade_pcp: index + 1 })));
      toast.success("Prioridades atualizadas");
      await fetchOrders();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Erro ao salvar prioridades");
    } finally {
      setSavingPriority(false);
    }
  };

  const movePriority = async (orderId, direction) => {
    const current = priorityDraft.length ? [...priorityDraft] : priorityBaseRows.map(row => row.id);
    const index = current.indexOf(orderId);
    const nextIndex = index + direction;
    if (index < 0 || nextIndex < 0 || nextIndex >= current.length) return;
    [current[index], current[nextIndex]] = [current[nextIndex], current[index]];
    setPriorityDraft(current);
    await persistPriority(current);
  };

  const movePriorityTo = async (orderId, targetPosition) => {
    const current = priorityDraft.length ? [...priorityDraft] : priorityBaseRows.map(row => row.id);
    const index = current.indexOf(orderId);
    if (index < 0) return;
    const pos = Math.max(1, Math.min(current.length, Number(targetPosition || 1))) - 1;
    current.splice(index, 1);
    current.splice(pos, 0, orderId);
    setPriorityDraft(current);
    await persistPriority(current);
  };

  const createOp = async (order, event) => {
    event?.stopPropagation();
    setCreatingOpId(order.id);
    try {
      const res = await api.post(`/orders/${order.id}/create-op`);
      toast.success(`OP ${res.data.numero_op} enviada ao PCP`);
      await fetchOrders();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Erro ao gerar OP");
    } finally {
      setCreatingOpId("");
    }
  };

  const groupedProduction = useMemo(() => {
    if (groupBy === "none") return [{ key: "todos", label: "Todos os pedidos", rows: productionRows }];
    const groups = new Map();
    for (const row of productionRows) {
      const key = groupBy === "linha" ? row.linha : row.cliente;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(row);
    }
    return Array.from(groups.entries()).map(([key, rows]) => ({ key, label: key, rows }));
  }, [productionRows, groupBy]);

  return (
    <div className="h-full overflow-auto bg-background">
      <div className="mx-auto max-w-[1500px] space-y-5 p-4 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-heading font-semibold tracking-tight">
              <ShoppingCart className="h-6 w-6" />
              Pedidos
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Pedido comercial, OP e PCP no mesmo fluxo operacional.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={fetchOrders} className="gap-1.5">
              <RefreshCw className="h-4 w-4" /> Atualizar
            </Button>
            <Button onClick={() => navigate("/orders/gerador")} className="gap-1.5">
              <FileText className="h-4 w-4" /> Gerador de Pedidos
            </Button>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
          <StatCard label="Total" value={counts.total} icon={ClipboardList} color="text-slate-600 dark:text-slate-300" />
          <StatCard label="Em andamento" value={counts.andamento} icon={Clock3} color="text-blue-600" />
          <StatCard label="Sem OP" value={counts.semOp} icon={Factory} color="text-amber-600" />
          <StatCard label="Sem PCP" value={counts.semPcp} icon={Route} color="text-indigo-600" />
          <StatCard label="Concluidos" value={counts.concluido} icon={CheckCircle2} color="text-green-600" />
          <StatCard label="Valor Total" value={formatCurrencyBR(counts.valor_total)} color="text-green-600" icon={DollarSign} isText />
        </div>

        {generatedStatus?.total > 0 && (
          <Card className="border-blue-200 bg-blue-50/60 dark:border-blue-900 dark:bg-blue-950/20">
            <CardContent className="p-4">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                <div>
                  <p className="flex items-center gap-2 text-sm font-semibold">
                    <FileText className="h-4 w-4 text-blue-600" /> Status dos pedidos do Gerador
                  </p>
                  <p className="text-xs text-muted-foreground">
                    Pedido gerado, confirmacao do cliente, aprovacao comercial, OP e anexo na mesma esteira.
                  </p>
                </div>
                <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap">
                  <GeneratorPill label="Gerados" value={generatedStatus.total} />
                  <GeneratorPill label="Com anexo" value={generatedStatus.com_anexo} />
                  <GeneratorPill label="PDF gerado" value={generatedStatus.pdf_gerado} />
                  <GeneratorPill label="Aguard. cliente" value={generatedStatus.aguardando_cliente} />
                  <GeneratorPill label="Aguard. comercial" value={generatedStatus.aguardando_comercial} />
                  <GeneratorPill label="Com OP" value={generatedStatus.com_op} />
                </div>
              </div>
            </CardContent>
          </Card>
        )}

        <Card>
          <CardContent className="space-y-3 p-4">
            <div className="grid gap-2 lg:grid-cols-[1fr_180px_180px_180px]">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  placeholder="Buscar por pedido, cliente, produto, SKU ou projeto..."
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="pl-9"
                  data-testid="orders-search-input"
                />
              </div>
              <Select value={statusFilter} onValueChange={setStatusFilter}>
                <SelectTrigger data-testid="orders-status-filter"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="andamento">Em andamento</SelectItem>
                  <SelectItem value="all">Todos os Status</SelectItem>
                  <SelectItem value="rascunho">Rascunho</SelectItem>
                  <SelectItem value="confirmado">Confirmado</SelectItem>
                  <SelectItem value="em_producao">Em Producao</SelectItem>
                  <SelectItem value="concluido">Concluido</SelectItem>
                  <SelectItem value="cancelado">Cancelado</SelectItem>
                </SelectContent>
              </Select>
              <Select value={lineFilter} onValueChange={setLineFilter}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Todas as linhas</SelectItem>
                  {lineOptions.map(line => <SelectItem key={line} value={line}>{line}</SelectItem>)}
                </SelectContent>
              </Select>
              <Select value={groupBy} onValueChange={setGroupBy}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">Sem agrupamento</SelectItem>
                  <SelectItem value="linha">Agrupar por linha</SelectItem>
                  <SelectItem value="cliente">Agrupar por cliente</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Select value={followupFilter} onValueChange={setFollowupFilter}>
                <SelectTrigger className="w-full sm:w-52" data-testid="orders-followup-filter">
                  <Bell className="mr-1 h-3.5 w-3.5" />
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Follow-up: Todos</SelectItem>
                  <SelectItem value="1m">Follow-up 1 mes</SelectItem>
                  <SelectItem value="3m">Follow-up 3 meses</SelectItem>
                  <SelectItem value="6m">Follow-up 6 meses</SelectItem>
                  <SelectItem value="pendente">Com follow-up pendente</SelectItem>
                </SelectContent>
              </Select>
              <Badge variant="outline" className="gap-1.5 rounded-md px-2 py-1 text-xs">
                <SlidersHorizontal className="h-3.5 w-3.5" />
                {productionRows.length} SKU(s) visiveis
              </Badge>
            </div>
          </CardContent>
        </Card>

        <Tabs value={tab} onValueChange={setTab} className="space-y-4">
          <TabsList className="h-auto flex-wrap justify-start">
            <TabsTrigger value="producao" className="gap-1.5">
              <PackageCheck className="h-4 w-4" /> Pedidos - SKUs para Producao
            </TabsTrigger>
            <TabsTrigger value="comerciais" className="gap-1.5">
              <ClipboardList className="h-4 w-4" /> Pedidos Comerciais
            </TabsTrigger>
            <TabsTrigger value="prioridades" className="gap-1.5">
              <GripVertical className="h-4 w-4" /> Ordenar Prioridades
            </TabsTrigger>
          </TabsList>

          <TabsContent value="producao">
            {loading ? <LoadingState /> : productionRows.length === 0 ? <EmptyState /> : (
              <div className="space-y-4">
                {groupedProduction.map(group => (
                  <Card key={group.key}>
                    <CardContent className="p-0">
                      {groupBy !== "none" && (
                        <div className="flex items-center justify-between border-b px-4 py-3">
                          <div className="flex items-center gap-2 font-semibold">
                            <Layers3 className="h-4 w-4 text-primary" /> {group.label}
                          </div>
                          <Badge variant="outline">{group.rows.length} SKU(s)</Badge>
                        </div>
                      )}
                      <ProductionTable rows={group.rows} navigate={navigate} createOp={createOp} creatingOpId={creatingOpId} />
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </TabsContent>

          <TabsContent value="comerciais">
            {loading ? <LoadingState /> : commercialRows.length === 0 ? <EmptyState /> : (
              <Card>
                <CardContent className="p-0">
                  <CommercialTable rows={commercialRows} navigate={navigate} createOp={createOp} creatingOpId={creatingOpId} />
                </CardContent>
              </Card>
            )}
          </TabsContent>

          <TabsContent value="prioridades">
            <PriorityPanel
              rows={(priorityDraft.length ? priorityDraft : priorityBaseRows.map(row => row.id)).map(id => priorityRowsById.get(id)).filter(Boolean)}
              saving={savingPriority}
              movePriority={movePriority}
              movePriorityTo={movePriorityTo}
              navigate={navigate}
            />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}

function ProductionTable({ rows, navigate, createOp, creatingOpId }) {
  return (
    <>
      <div className="hidden overflow-x-auto md:block">
        <table className="w-full min-w-[1120px] text-sm">
          <thead>
            <tr className="border-b bg-muted/40 text-left text-[11px] uppercase tracking-wide text-muted-foreground">
              <th className="p-3">ID</th>
              <th className="p-3">Cliente</th>
              <th className="p-3">Produto</th>
              <th className="p-3">SKU</th>
              <th className="p-3 text-right">Qtd Total</th>
              <th className="p-3 text-right">Produzido</th>
              <th className="p-3">%</th>
              <th className="p-3">Linha</th>
              <th className="p-3">Data prod.</th>
              <th className="p-3">Data pedido</th>
              <th className="p-3">Aberto ha</th>
              <th className="p-3">Fluxo</th>
              <th className="p-3 text-right">Acoes</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(row => (
              <tr key={row.id} className="border-b transition-colors hover:bg-accent/40">
                <td className="p-3 align-top">
                  <button className="font-mono text-xs font-bold text-primary" onClick={() => navigate(`/orders/${row.order.id}`)}>
                    #{row.order.numero_pedido}
                  </button>
                  {row.op?.numero_op && <div className="mt-1 font-mono text-[11px] text-muted-foreground">{row.op.numero_op}</div>}
                </td>
                <td className="p-3 align-top">
                  <div className="flex max-w-[150px] items-center gap-1.5">
                    <Building2 className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                    <span className="truncate">{row.cliente}</span>
                  </div>
                </td>
                <td className="p-3 align-top">
                  <div className="max-w-[220px] truncate font-semibold">{row.produto}</div>
                  <OrderBadges order={row.order} />
                </td>
                <td className="p-3 align-top font-mono text-xs">{row.sku}</td>
                <td className="p-3 text-right align-top font-semibold">{numberBR(row.qtdTotal)}</td>
                <td className="p-3 text-right align-top">{numberBR(row.qtdProduzida)}</td>
                <td className="w-36 p-3 align-top"><ProgressCell value={row.progress} /></td>
                <td className="p-3 align-top"><Badge variant="outline">{row.linha}</Badge></td>
                <td className="p-3 align-top text-muted-foreground">{formatDateBR(row.dataProducao)}</td>
                <td className="p-3 align-top text-muted-foreground">{formatDateBR(row.order.data_pedido || row.order.created_at)}</td>
                <td className="p-3 align-top"><AgeBadge days={row.openedDays} /></td>
                <td className="p-3 align-top"><FlowBadges order={row.order} op={row.op} slot={row.slot} /></td>
                <td className="p-3 text-right align-top">
                  {row.op ? (
                    <Button size="sm" variant="outline" onClick={() => navigate(`/ops/${row.op.id}`)}>Ver OP</Button>
                  ) : (
                    <Button
                      size="sm"
                      disabled={!["confirmado", "em_producao"].includes(row.order.status) || creatingOpId === row.order.id}
                      onClick={(event) => createOp(row.order, event)}
                    >
                      {creatingOpId === row.order.id ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <Factory className="mr-1 h-3.5 w-3.5" />}
                      Gerar OP
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="space-y-3 p-3 md:hidden">
        {rows.map(row => (
          <MobileProductionCard key={row.id} row={row} navigate={navigate} createOp={createOp} creatingOpId={creatingOpId} />
        ))}
      </div>
    </>
  );
}

function CommercialTable({ rows, navigate, createOp, creatingOpId }) {
  return (
    <>
      <div className="hidden overflow-x-auto md:block">
        <table className="w-full min-w-[980px] text-sm">
          <thead>
            <tr className="border-b bg-muted/40 text-left text-[11px] uppercase tracking-wide text-muted-foreground">
              <th className="p-3">Pedido</th>
              <th className="p-3">Cliente</th>
              <th className="p-3">Itens/SKUs</th>
              <th className="p-3 text-right">Qtd Pedida</th>
              <th className="p-3 text-right">Produzido</th>
              <th className="p-3">%</th>
              <th className="p-3">Data pedido</th>
              <th className="p-3">Aberto ha</th>
              <th className="p-3">Pedido / OP / PCP</th>
              <th className="p-3 text-right">Acoes</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(row => (
              <tr key={row.id} className="border-b transition-colors hover:bg-accent/40">
                <td className="p-3 align-top">
                  <button className="font-mono text-xs font-bold text-primary" onClick={() => navigate(`/orders/${row.order.id}`)}>
                    #{row.order.numero_pedido}
                  </button>
                  <div className="mt-1 text-[11px] text-muted-foreground">Prioridade {row.prioridade === 9999 ? "-" : row.prioridade}</div>
                </td>
                <td className="p-3 align-top font-medium">{row.cliente}</td>
                <td className="p-3 align-top">
                  <div className="max-w-[260px] space-y-1">
                    {(row.order.items || []).slice(0, 3).map((item, index) => (
                      <div key={`${row.id}-${index}`} className="truncate text-xs">
                        <span className="font-semibold">{item.codigo_kuryos || "A definir"}</span> - {item.item}
                      </div>
                    ))}
                    {(row.order.items || []).length > 3 && <div className="text-xs text-muted-foreground">+{row.order.items.length - 3} item(ns)</div>}
                  </div>
                </td>
                <td className="p-3 text-right align-top font-semibold">{numberBR(row.qtdTotal)}</td>
                <td className="p-3 text-right align-top">{numberBR(row.qtdProduzida)}</td>
                <td className="w-36 p-3 align-top"><ProgressCell value={row.progress} /></td>
                <td className="p-3 align-top text-muted-foreground">{formatDateBR(row.order.data_pedido || row.order.created_at)}</td>
                <td className="p-3 align-top"><AgeBadge days={row.openedDays} /></td>
                <td className="p-3 align-top"><FlowBadges order={row.order} op={row.ops[0]} slot={row.slot} /></td>
                <td className="p-3 text-right align-top">
                  {row.ops[0] ? (
                    <Button size="sm" variant="outline" onClick={() => navigate(`/ops/${row.ops[0].id}`)}>Ver OP</Button>
                  ) : (
                    <Button
                      size="sm"
                      disabled={!["confirmado", "em_producao"].includes(row.order.status) || creatingOpId === row.order.id}
                      onClick={(event) => createOp(row.order, event)}
                    >
                      {creatingOpId === row.order.id ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <Factory className="mr-1 h-3.5 w-3.5" />}
                      Gerar OP
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="space-y-3 p-3 md:hidden">
        {rows.map(row => (
          <Card key={row.id} className="border-border/70">
            <CardContent className="space-y-3 p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <button className="font-mono text-sm font-bold text-primary" onClick={() => navigate(`/orders/${row.order.id}`)}>
                    #{row.order.numero_pedido}
                  </button>
                  <h3 className="truncate font-semibold">{row.cliente}</h3>
                </div>
                <AgeBadge days={row.openedDays} />
              </div>
              <ProgressCell value={row.progress} />
              <FlowBadges order={row.order} op={row.ops[0]} slot={row.slot} />
              <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                <span>Qtd: <strong className="text-foreground">{numberBR(row.qtdTotal)}</strong></span>
                <span>Produzido: <strong className="text-foreground">{numberBR(row.qtdProduzida)}</strong></span>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </>
  );
}

function PriorityPanel({ rows, saving, movePriority, movePriorityTo, navigate }) {
  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="flex items-center gap-2 text-base font-semibold">
              <GripVertical className="h-4 w-4" /> Prioridades de Pedidos
            </h2>
            <p className="text-sm text-muted-foreground">
              A ordem salva no pedido alimenta a leitura comercial e a priorizacao do PCP.
            </p>
          </div>
          {saving && <Badge variant="outline"><Loader2 className="mr-1 h-3 w-3 animate-spin" /> Salvando</Badge>}
        </div>
        {rows.length === 0 ? <EmptyState /> : (
          <div className="space-y-2">
            {rows.map((row, index) => (
              <div key={row.id} className="grid gap-3 rounded-lg border bg-card p-3 md:grid-cols-[42px_1fr_110px_150px] md:items-center">
                <div className="flex h-9 w-9 items-center justify-center rounded-md bg-primary text-sm font-bold text-primary-foreground">
                  {index + 1}
                </div>
                <div className="min-w-0">
                  <button className="font-mono text-xs font-bold text-primary" onClick={() => navigate(`/orders/${row.order.id}`)}>
                    #{row.order.numero_pedido}
                  </button>
                  <div className="truncate font-semibold">{row.cliente}</div>
                  <div className="truncate text-xs text-muted-foreground">
                    {(row.order.items || []).map(item => item.item).filter(Boolean).join(" | ") || row.order.project_name || "Sem itens"}
                  </div>
                </div>
                <Input
                  type="number"
                  min="1"
                  max={rows.length}
                  value={index + 1}
                  disabled={saving}
                  onChange={(event) => movePriorityTo(row.id, event.target.value)}
                  className="h-9 text-center"
                  aria-label="Posicao da prioridade"
                />
                <div className="flex gap-2 md:justify-end">
                  <Button size="icon" variant="outline" disabled={saving || index === 0} onClick={() => movePriority(row.id, -1)}>
                    <ArrowUp className="h-4 w-4" />
                  </Button>
                  <Button size="icon" variant="outline" disabled={saving || index === rows.length - 1} onClick={() => movePriority(row.id, 1)}>
                    <ArrowDown className="h-4 w-4" />
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => navigate(`/orders/${row.order.id}`)}>
                    Abrir
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function MobileProductionCard({ row, navigate, createOp, creatingOpId }) {
  return (
    <Card className="border-border/70">
      <CardContent className="space-y-3 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <button className="font-mono text-sm font-bold text-primary" onClick={() => navigate(`/orders/${row.order.id}`)}>
              #{row.order.numero_pedido}
            </button>
            <h3 className="truncate font-semibold">{row.produto}</h3>
            <p className="truncate text-xs text-muted-foreground">{row.cliente} - {row.sku}</p>
          </div>
          <Badge variant="outline">{row.linha}</Badge>
        </div>
        <ProgressCell value={row.progress} />
        <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground">
          <span>Qtd: <strong className="text-foreground">{numberBR(row.qtdTotal)}</strong></span>
          <span>Produzido: <strong className="text-foreground">{numberBR(row.qtdProduzida)}</strong></span>
          <span>Pedido: <strong className="text-foreground">{formatDateBR(row.order.data_pedido || row.order.created_at)}</strong></span>
          <span>Producao: <strong className="text-foreground">{formatDateBR(row.dataProducao)}</strong></span>
        </div>
        <FlowBadges order={row.order} op={row.op} slot={row.slot} />
        <div className="flex justify-end">
          {row.op ? (
            <Button size="sm" variant="outline" onClick={() => navigate(`/ops/${row.op.id}`)}>Ver OP</Button>
          ) : (
            <Button
              size="sm"
              disabled={!["confirmado", "em_producao"].includes(row.order.status) || creatingOpId === row.order.id}
              onClick={(event) => createOp(row.order, event)}
            >
              {creatingOpId === row.order.id ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <Factory className="mr-1 h-3.5 w-3.5" />}
              Gerar OP
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function FlowBadges({ order, op, slot }) {
  const orderCfg = STATUS_CONFIG[order.status] || STATUS_CONFIG.rascunho;
  const opCfg = op ? (OP_STATUS_CONFIG[op.status] || OP_STATUS_CONFIG.aberta) : null;
  const slotCfg = slot ? (PCP_STATUS_CONFIG[slot.status] || PCP_STATUS_CONFIG.planejado) : null;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Badge className={`${orderCfg.color} text-[10px]`}>Pedido: {orderCfg.label}</Badge>
      <ArrowRight className="h-3 w-3 text-muted-foreground" />
      {op ? <Badge className={`${opCfg.color} text-[10px]`}>{opCfg.label}</Badge> : <Badge variant="outline" className="text-[10px]">OP pendente</Badge>}
      <ArrowRight className="h-3 w-3 text-muted-foreground" />
      {slot ? <Badge className={`${slotCfg.color} text-[10px]`}>{slotCfg.label}</Badge> : <Badge variant="outline" className="text-[10px]">PCP pendente</Badge>}
    </div>
  );
}

function OrderBadges({ order }) {
  const fuState = getOrderFollowupState(order);
  return (
    <div className="mt-1 flex flex-wrap gap-1">
      {order.auto_created && <Badge variant="outline" className="text-[10px]">Auto-gerado</Badge>}
      {order.origem === "direto" && <Badge variant="outline" className="border-cyan-300 text-[10px] text-cyan-700">Pedido direto</Badge>}
      {(order.origem === "gerador" || order.gerador_origem) && <Badge variant="outline" className="border-blue-300 text-[10px] text-blue-700">Gerador</Badge>}
      {(order.attachments || []).length > 0 && <Badge variant="outline" className="gap-1 border-emerald-300 text-[10px] text-emerald-700"><Paperclip className="h-2.5 w-2.5" />Anexo</Badge>}
      {order.pdf?.generated_at && <Badge variant="outline" className="gap-1 border-green-300 text-[10px] text-green-700"><Download className="h-2.5 w-2.5" />PDF</Badge>}
      {fuState && <Badge className={`gap-1 text-[10px] ${fuState.color}`}><Bell className="h-2.5 w-2.5" />{fuState.label}</Badge>}
    </div>
  );
}

function ProgressCell({ value }) {
  const color = value >= 95 ? "bg-green-500" : value >= 70 ? "bg-amber-500" : "bg-primary";
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between gap-2">
        <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
          <div className={`h-full rounded-full ${color}`} style={{ width: `${value}%` }} />
        </div>
        <span className="w-10 text-right text-xs font-bold">{value}%</span>
      </div>
    </div>
  );
}

function AgeBadge({ days }) {
  const color = days > 7 ? "border-red-300 text-red-700 dark:text-red-300" : days > 2 ? "border-amber-300 text-amber-700 dark:text-amber-300" : "border-green-300 text-green-700 dark:text-green-300";
  return <Badge variant="outline" className={`${color} whitespace-nowrap`}>{days} dia(s)</Badge>;
}

function LoadingState() {
  return (
    <div className="flex items-center justify-center py-20">
      <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
    </div>
  );
}

function EmptyState() {
  return (
    <Card className="border-dashed">
      <CardContent className="py-16 text-center">
        <ClipboardList className="mx-auto mb-4 h-14 w-14 text-muted-foreground/30" />
        <h3 className="mb-1 text-lg font-semibold">Nenhum pedido encontrado</h3>
        <p className="mx-auto max-w-md text-sm text-muted-foreground">
          Ajuste os filtros ou gere um pedido comercial para acompanhar OP e PCP por aqui.
        </p>
      </CardContent>
    </Card>
  );
}

function StatCard({ label, value, icon: Icon, color, isText }) {
  return (
    <Card>
      <CardContent className="p-3">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="truncate text-[11px] uppercase tracking-wider text-muted-foreground">{label}</div>
            <div className={`mt-0.5 truncate font-bold ${color || ""} ${isText ? "text-base" : "text-2xl"}`}>{value}</div>
          </div>
          {Icon && <Icon className={`h-5 w-5 shrink-0 ${color || "text-muted-foreground"} opacity-60`} />}
        </div>
      </CardContent>
    </Card>
  );
}

function GeneratorPill({ label, value }) {
  return (
    <div className="rounded-md border bg-background/80 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="text-base font-bold">{value ?? 0}</div>
    </div>
  );
}
