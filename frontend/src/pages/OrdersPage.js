import React, { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";
import { ClipboardList, Search, Loader2, FileText, ArrowRight, Building2, Calendar, DollarSign, Bell, Plus, Paperclip, Download } from "lucide-react";

const STATUS_CONFIG = {
  rascunho: { label: "Rascunho", color: "bg-slate-500/10 text-slate-600 border-slate-300 dark:text-slate-300" },
  confirmado: { label: "Confirmado", color: "bg-blue-500/10 text-blue-600 border-blue-300 dark:text-blue-300" },
  em_producao: { label: "Em Produção", color: "bg-amber-500/10 text-amber-700 border-amber-300 dark:text-amber-300" },
  concluido: { label: "Concluído", color: "bg-green-500/10 text-green-700 border-green-300 dark:text-green-300" },
  cancelado: { label: "Cancelado", color: "bg-red-500/10 text-red-700 border-red-300 dark:text-red-300" },
};

function formatCurrencyBR(value) {
  if (!value && value !== 0) return "R$ 0,00";
  return `R$ ${Number(value).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatDateBR(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleDateString("pt-BR"); } catch { return iso; }
}

const FOLLOWUP_LABELS = { "1m": "1 mês", "3m": "3 meses", "6m": "6 meses" };

function getOrderFollowupState(order) {
  const now = new Date();
  const fus = order.followups || [];
  if (!fus.length) return null;
  const pending = fus.filter(fu => !fu.notificado);
  if (!pending.length) return { label: "Todos notificados", color: "bg-green-100 text-green-700", marco: null };
  const next = pending.reduce((a, b) => new Date(a.vence_em) <= new Date(b.vence_em) ? a : b);
  const overdue = new Date(next.vence_em) < now;
  return {
    label: `Follow-up ${next.marco}${overdue ? " (vencido)" : ""}`,
    color: overdue ? "bg-red-100 text-red-700" : "bg-amber-100 text-amber-700",
    marco: next.marco,
    overdue,
  };
}

export default function OrdersPage() {
  const navigate = useNavigate();
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [followupFilter, setFollowupFilter] = useState("all");
  const [generatedStatus, setGeneratedStatus] = useState(null);

  const fetchOrders = useCallback(async () => {
    setLoading(true);
    try {
      const params = {};
      if (statusFilter !== "all") params.status = statusFilter;
      if (search.trim()) params.q = search.trim();
      const [res, generatorRes] = await Promise.all([
        api.get("/orders", { params }),
        api.get("/orders/generated/status").catch(() => ({ data: null })),
      ]);
      setOrders(res.data || []);
      setGeneratedStatus(generatorRes.data);
    } catch (err) {
      toast.error("Erro ao carregar pedidos");
    } finally {
      setLoading(false);
    }
  }, [statusFilter, search]);

  useEffect(() => { fetchOrders(); }, [fetchOrders]);

  const counts = {
    total: orders.length,
    rascunho: orders.filter(o => o.status === "rascunho").length,
    confirmado: orders.filter(o => o.status === "confirmado").length,
    em_producao: orders.filter(o => o.status === "em_producao").length,
    concluido: orders.filter(o => o.status === "concluido").length,
    valor_total: orders.reduce((s, o) => s + (o.total_pedido || 0), 0),
  };

  return (
    <div className="h-full overflow-auto">
      <div className="max-w-7xl mx-auto p-6 space-y-5">
        {/* Header */}
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-2xl font-heading font-semibold tracking-tight flex items-center gap-2">
              <ClipboardList className="h-6 w-6" />
              Pedidos de Industrialização (PI)
            </h1>
            <p className="text-sm text-muted-foreground mt-1">
              Pedidos comerciais gerados a partir de projetos P&D aprovados
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => navigate("/orders/gerador")} className="gap-1.5">
              <FileText className="h-4 w-4" /> Gerador de Pedidos
            </Button>
          </div>
        </div>

        {/* Mini stats */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <StatCard label="Total" value={counts.total} icon={ClipboardList} color="text-slate-600 dark:text-slate-300" />
          <StatCard label="Rascunho" value={counts.rascunho} color="text-slate-500" />
          <StatCard label="Confirmado" value={counts.confirmado} color="text-blue-600" />
          <StatCard label="Em Produção" value={counts.em_producao} color="text-amber-600" />
          <StatCard label="Valor Total" value={formatCurrencyBR(counts.valor_total)} color="text-green-600" icon={DollarSign} isText />
        </div>

        {generatedStatus?.total > 0 && (
          <Card className="border-blue-200 bg-blue-50/50 dark:border-blue-900 dark:bg-blue-950/20">
            <CardContent className="p-4">
              <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <div>
                  <p className="text-sm font-semibold flex items-center gap-2">
                    <FileText className="h-4 w-4 text-blue-600" /> Status dos pedidos do Gerador
                  </p>
                  <p className="text-xs text-muted-foreground">
                    Visao minima integrada nesta tela, sem duplicar cadastro/listagem de pedidos.
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <GeneratorPill label="Gerados" value={generatedStatus.total} />
                  <GeneratorPill label="Com anexo" value={generatedStatus.com_anexo} />
                  <GeneratorPill label="PDF gerado" value={generatedStatus.pdf_gerado} />
                  <GeneratorPill label="Aguard. cliente" value={generatedStatus.aguardando_cliente} />
                  <GeneratorPill label="Com OP" value={generatedStatus.com_op} />
                </div>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Filters */}
        <div className="flex gap-2 items-center flex-wrap">
          <div className="relative flex-1 min-w-[240px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Buscar por nº, cliente, projeto..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9"
              data-testid="orders-search-input"
            />
          </div>
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="w-44" data-testid="orders-status-filter">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Todos os Status</SelectItem>
              <SelectItem value="rascunho">Rascunho</SelectItem>
              <SelectItem value="confirmado">Confirmado</SelectItem>
              <SelectItem value="em_producao">Em Produção</SelectItem>
              <SelectItem value="concluido">Concluído</SelectItem>
              <SelectItem value="cancelado">Cancelado</SelectItem>
            </SelectContent>
          </Select>
          <Select value={followupFilter} onValueChange={setFollowupFilter}>
            <SelectTrigger className="w-44" data-testid="orders-followup-filter">
              <Bell className="h-3.5 w-3.5 mr-1" />
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Follow-up: Todos</SelectItem>
              <SelectItem value="1m">Follow-up 1 mês</SelectItem>
              <SelectItem value="3m">Follow-up 3 meses</SelectItem>
              <SelectItem value="6m">Follow-up 6 meses</SelectItem>
              <SelectItem value="pendente">Com follow-up pendente</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* List */}
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : orders.length === 0 ? (
          <Card className="border-dashed">
            <CardContent className="py-16 text-center">
              <ClipboardList className="h-14 w-14 mx-auto mb-4 text-muted-foreground/30" />
              <h3 className="text-lg font-semibold mb-1">Nenhum pedido ainda</h3>
              <p className="text-sm text-muted-foreground max-w-md mx-auto">
                Quando um projeto P&D for aprovado pelo cliente (status APROVADO), uma Ordem de Produção será criada automaticamente aqui.
              </p>
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-2">
            {orders
              .filter(order => {
                if (followupFilter === "all") return true;
                const fus = order.followups || [];
                if (followupFilter === "pendente") return fus.some(fu => !fu.notificado);
                return fus.some(fu => fu.marco === followupFilter && !fu.notificado);
              })
              .map(order => {
              const cfg = STATUS_CONFIG[order.status] || STATUS_CONFIG.rascunho;
              const fuState = getOrderFollowupState(order);
              return (
                <Card
                  key={order.id}
                  className="hover:border-primary/40 hover:shadow-sm transition-all cursor-pointer group"
                  onClick={() => navigate(`/orders/${order.id}`)}
                  data-testid={`order-card-${order.id}`}
                >
                  <CardContent className="p-4">
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                          <span className="font-mono text-sm font-bold text-primary">#{order.numero_pedido}</span>
                          <Badge className={`${cfg.color} text-[10px]`}>{cfg.label}</Badge>
                          {order.auto_created && (
                            <Badge variant="outline" className="text-[10px] gap-1">
                              <FileText className="h-2.5 w-2.5" />
                              Auto-gerado
                            </Badge>
                          )}
                          {order.origem === "direto" && (
                            <Badge variant="outline" className="text-[10px] gap-1 border-cyan-300 text-cyan-700">
                              <Plus className="h-2.5 w-2.5" />
                              Pedido Direto
                            </Badge>
                          )}
                          {(order.origem === "gerador" || order.gerador_origem) && (
                            <Badge variant="outline" className="text-[10px] gap-1 border-blue-300 text-blue-700">
                              <FileText className="h-2.5 w-2.5" />
                              Gerador
                            </Badge>
                          )}
                          {(order.attachments || []).length > 0 && (
                            <Badge variant="outline" className="text-[10px] gap-1 border-emerald-300 text-emerald-700">
                              <Paperclip className="h-2.5 w-2.5" />
                              Anexo
                            </Badge>
                          )}
                          {order.pdf?.generated_at && (
                            <Badge variant="outline" className="text-[10px] gap-1 border-green-300 text-green-700">
                              <Download className="h-2.5 w-2.5" />
                              PDF
                            </Badge>
                          )}
                          {order.reproducao_de && (
                            <Badge variant="outline" className="text-[10px] gap-1 border-violet-300 text-violet-700">
                              Reprodução
                            </Badge>
                          )}
                          {fuState && (
                            <Badge className={`text-[10px] gap-1 ${fuState.color}`}>
                              <Bell className="h-2.5 w-2.5" />
                              {fuState.label}
                            </Badge>
                          )}
                        </div>
                        <h3 className="font-semibold text-base truncate">
                          {order.project_name || order.cliente?.nome || "Pedido sem nome"}
                        </h3>
                        <div className="flex items-center gap-4 mt-1.5 text-xs text-muted-foreground flex-wrap">
                          <span className="flex items-center gap-1">
                            <Building2 className="h-3 w-3" />
                            {order.cliente?.razao_social || order.cliente?.nome || "—"}
                          </span>
                          <span className="flex items-center gap-1">
                            <Calendar className="h-3 w-3" />
                            {formatDateBR(order.data_pedido)}
                          </span>
                          <span>{(order.items || []).length} item(ns)</span>
                        </div>
                      </div>
                      <div className="text-right shrink-0">
                        <div className="text-xs text-muted-foreground">Total</div>
                        <div className="text-lg font-bold text-green-600">
                          {formatCurrencyBR(order.total_pedido)}
                        </div>
                        <ArrowRight className="h-4 w-4 ml-auto mt-1 text-muted-foreground group-hover:text-primary transition-colors" />
                      </div>
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function StatCard({ label, value, icon: Icon, color, isText }) {
  return (
    <Card>
      <CardContent className="p-3">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-[11px] text-muted-foreground uppercase tracking-wider">{label}</div>
            <div className={`font-bold mt-0.5 ${color || ""} ${isText ? "text-base" : "text-2xl"}`}>{value}</div>
          </div>
          {Icon && <Icon className={`h-5 w-5 ${color || "text-muted-foreground"} opacity-60`} />}
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
