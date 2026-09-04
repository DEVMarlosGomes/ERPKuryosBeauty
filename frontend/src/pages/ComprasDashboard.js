import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import {
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  ChevronRight,
  ClipboardList,
  Copy,
  FileText,
  Handshake,
  Loader2,
  Package,
  Plus,
  RefreshCw,
  Send,
  ShoppingCart,
  Tag,
  Truck,
  Warehouse,
} from "lucide-react";

const DEMANDA_STATUS = {
  pendente: { label: "Pendente", cls: "border-amber-300 bg-amber-50 text-amber-700 dark:bg-amber-950/20 dark:text-amber-300" },
  em_cotacao: { label: "Em cotacao", cls: "border-blue-300 bg-blue-50 text-blue-700 dark:bg-blue-950/20 dark:text-blue-300" },
  po_emitida: { label: "PO emitida", cls: "border-green-300 bg-green-50 text-green-700 dark:bg-green-950/20 dark:text-green-300" },
  cancelada: { label: "Cancelada", cls: "border-red-300 bg-red-50 text-red-700 dark:bg-red-950/20 dark:text-red-300" },
};

const PO_STATUS = {
  rascunho: { label: "Rascunho", cls: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200" },
  emitida: { label: "Emitida", cls: "bg-blue-100 text-blue-700 dark:bg-blue-950/30 dark:text-blue-300" },
  confirmada: { label: "Confirmada", cls: "bg-indigo-100 text-indigo-700 dark:bg-indigo-950/30 dark:text-indigo-300" },
  parcialmente_recebida: { label: "Parc. recebida", cls: "bg-yellow-100 text-yellow-700 dark:bg-yellow-950/30 dark:text-yellow-300" },
  recebida: { label: "Recebida", cls: "bg-green-100 text-green-700 dark:bg-green-950/30 dark:text-green-300" },
  encerrada: { label: "Encerrada", cls: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300" },
  cancelada: { label: "Cancelada", cls: "bg-red-100 text-red-700 dark:bg-red-950/30 dark:text-red-300" },
};

const FRETES = ["cif", "fob", "valor_fixo", "percentual"];

function fmtBRL(value) {
  return Number(value || 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function fmt(value) {
  return Number(value || 0).toLocaleString("pt-BR", { maximumFractionDigits: 3 });
}

function dateBR(value) {
  if (!value) return "-";
  try {
    return new Date(value).toLocaleDateString("pt-BR");
  } catch {
    return value;
  }
}

function normalize(value) {
  return String(value || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
}

function statusBadge(status) {
  const cfg = DEMANDA_STATUS[status] || DEMANDA_STATUS.pendente;
  return <Badge variant="outline" className={`${cfg.cls} whitespace-nowrap`}>{cfg.label}</Badge>;
}

function poBadge(status) {
  const cfg = PO_STATUS[status] || PO_STATUS.rascunho;
  return <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${cfg.cls}`}>{cfg.label}</span>;
}

export default function ComprasDashboard() {
  const nav = useNavigate();
  const [loading, setLoading] = useState(true);
  const [dash, setDash] = useState(null);
  const [demandas, setDemandas] = useState([]);
  const [pos, setPos] = useState([]);
  const [itens, setItens] = useState([]);
  const [fornecedores, setFornecedores] = useState([]);
  const [historico, setHistorico] = useState([]);
  const [search, setSearch] = useState("");
  const [statusDemanda, setStatusDemanda] = useState("all");
  const [selectedDemandIds, setSelectedDemandIds] = useState([]);
  const [requestOpen, setRequestOpen] = useState(false);
  const [quoteOpen, setQuoteOpen] = useState(false);
  const [quoteDemand, setQuoteDemand] = useState(null);
  const [labelPO, setLabelPO] = useState(null);

  const carregar = useCallback(async () => {
    setLoading(true);
    try {
      const [dashRes, demandasRes, posRes, itensRes, fornecedoresRes, histRes] = await Promise.all([
        api.get("/compras/dashboard").catch(() => ({ data: null })),
        api.get("/compras/demandas", { params: { limit: 200 } }),
        api.get("/compras/pos", { params: { limit: 200 } }),
        api.get("/compras/itens", { params: { limit: 500 } }),
        api.get("/compras/fornecedores", { params: { limit: 500 } }),
        api.get("/compras/historico-precos", { params: { limit: 250 } }).catch(() => ({ data: { historico: [] } })),
      ]);
      setDash(dashRes.data);
      setDemandas(demandasRes.data?.demandas || []);
      setPos(posRes.data?.pos || []);
      setItens(itensRes.data?.itens || []);
      setFornecedores(fornecedoresRes.data?.fornecedores || []);
      setHistorico(histRes.data?.historico || []);
    } catch (err) {
      toast.error("Erro ao carregar compras");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { carregar(); }, [carregar]);

  const demandaRows = useMemo(() => {
    const q = normalize(search);
    return demandas.filter((d) => {
      if (statusDemanda !== "all" && d.status !== statusDemanda) return false;
      if (!q) return true;
      return normalize(`${d.numero_solicitacao} ${d.mrp_numero} ${d.item_codigo} ${d.item_descricao} ${d.solicitante_nome} ${d.motivo}`).includes(q);
    });
  }, [demandas, search, statusDemanda]);

  const selectedDemandas = useMemo(
    () => demandas.filter((d) => selectedDemandIds.includes(d.id)),
    [demandas, selectedDemandIds]
  );

  const metricas = useMemo(() => {
    const pendentes = demandas.filter(d => d.status === "pendente").length;
    const emCotacao = demandas.filter(d => d.status === "em_cotacao").length;
    const poAbertas = pos.filter(p => !["recebida", "encerrada", "cancelada"].includes(p.status)).length;
    const melhorPreco = historico.filter(h => Number(h.preco_unitario) === Number(h.menor_preco_item)).length;
    return {
      pendentes,
      emCotacao,
      poAbertas,
      melhorPreco,
      atrasadas: dash?.visao_operacional?.pos_atrasadas?.length || pos.filter(p => p.urgente).length,
      valorAberto: pos.filter(p => !["recebida", "encerrada", "cancelada"].includes(p.status)).reduce((s, p) => s + Number(p.valor_total_po || 0), 0),
    };
  }, [demandas, pos, historico, dash]);

  const openQuoteForDemand = async (demanda) => {
    setQuoteDemand(demanda);
    setQuoteOpen(true);
    if (demanda.status === "pendente") {
      try {
        await api.put(`/compras/demandas/${demanda.id}`, { status: "em_cotacao" });
        carregar();
      } catch {
        // abrir a cotacao ainda permite visualizar historico; o erro aparece ao salvar.
      }
    }
  };

  const startSelectedQuote = async () => {
    if (!selectedDemandas.length) {
      toast.error("Selecione pelo menos uma solicitacao");
      return;
    }
    try {
      await Promise.all(selectedDemandas.filter(d => d.status === "pendente").map(d => api.put(`/compras/demandas/${d.id}`, { status: "em_cotacao" })));
      toast.success(`${selectedDemandas.length} solicitacao(oes) em cotacao`);
      openQuoteForDemand(selectedDemandas[0]);
      setSelectedDemandIds([]);
      carregar();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Erro ao iniciar cotacao");
    }
  };

  const toggleDemand = (id) => {
    setSelectedDemandIds((current) => current.includes(id) ? current.filter(x => x !== id) : [...current, id]);
  };

  return (
    <div className="mx-auto max-w-[1500px] space-y-5 p-4 md:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-heading font-semibold tracking-tight">
            <Package className="h-6 w-6 text-primary" /> Compras
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Solicitacao, cotacao multi-fornecedor, pedido de compra, etiqueta e historico de precos.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={carregar} className="gap-1.5">
            <RefreshCw className="h-4 w-4" /> Atualizar
          </Button>
          <Button variant="outline" onClick={() => nav("/compras/mrp")} className="gap-1.5">
            <Warehouse className="h-4 w-4" /> MRP
          </Button>
          <Button onClick={() => setRequestOpen(true)} className="gap-1.5">
            <Plus className="h-4 w-4" /> Nova Solicitacao
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
        <MetricCard title="Solicitacoes pendentes" value={metricas.pendentes} icon={ClipboardList} tone="amber" />
        <MetricCard title="Em cotacao" value={metricas.emCotacao} icon={Handshake} tone="blue" />
        <MetricCard title="POs abertas" value={metricas.poAbertas} icon={ShoppingCart} tone="indigo" />
        <MetricCard title="POs atrasadas" value={metricas.atrasadas} icon={AlertTriangle} tone="red" />
        <MetricCard title="Melhores precos" value={metricas.melhorPreco} icon={CheckCircle2} tone="green" />
        <MetricCard title="Valor aberto" value={fmtBRL(metricas.valorAberto)} icon={BarChart3} tone="neutral" text />
      </div>

      <FlowStrip nav={nav} />

      <Tabs defaultValue="solicitacoes" className="space-y-4">
        <TabsList className="h-auto flex-wrap justify-start">
          <TabsTrigger value="solicitacoes" className="gap-1.5"><ClipboardList className="h-4 w-4" /> Solicitacoes</TabsTrigger>
          <TabsTrigger value="cotacoes" className="gap-1.5"><Handshake className="h-4 w-4" /> Cotacoes</TabsTrigger>
          <TabsTrigger value="pedidos" className="gap-1.5"><ShoppingCart className="h-4 w-4" /> Pedidos de Compra</TabsTrigger>
          <TabsTrigger value="precos" className="gap-1.5"><BarChart3 className="h-4 w-4" /> Historico de Precos</TabsTrigger>
          <TabsTrigger value="fornecedores" className="gap-1.5"><Truck className="h-4 w-4" /> Fornecedores</TabsTrigger>
        </TabsList>

        <TabsContent value="solicitacoes">
          <Card>
            <CardContent className="space-y-4 p-4">
              <div className="grid gap-2 md:grid-cols-[1fr_190px_auto]">
                <div className="relative">
                  <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Buscar por numero, material, solicitante ou motivo..." className="pl-9" />
                  <ClipboardList className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                </div>
                <Select value={statusDemanda} onValueChange={setStatusDemanda}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Todos os status</SelectItem>
                    {Object.entries(DEMANDA_STATUS).map(([k, cfg]) => <SelectItem key={k} value={k}>{cfg.label}</SelectItem>)}
                  </SelectContent>
                </Select>
                <Button variant="outline" onClick={startSelectedQuote} disabled={!selectedDemandIds.length} className="gap-1.5">
                  <Handshake className="h-4 w-4" /> Iniciar Cotacao ({selectedDemandIds.length})
                </Button>
              </div>
              {loading ? <Loading /> : <DemandasTable rows={demandaRows} selected={selectedDemandIds} toggle={toggleDemand} openQuote={openQuoteForDemand} nav={nav} />}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="cotacoes">
          <div className="grid gap-4 xl:grid-cols-[360px_1fr]">
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-sm">Fila para cotacao</CardTitle></CardHeader>
              <CardContent className="space-y-2">
                {demandas.filter(d => ["pendente", "em_cotacao"].includes(d.status)).slice(0, 12).map((d) => (
                  <button key={d.id} onClick={() => openQuoteForDemand(d)} className={`w-full rounded-lg border p-3 text-left transition hover:border-primary/40 ${quoteDemand?.id === d.id ? "border-primary bg-primary/5" : "bg-card"}`}>
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-sm font-semibold">{d.item_descricao}</span>
                      {statusBadge(d.status)}
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">{fmt(d.quantidade)} {d.unidade_compra || ""} - limite {dateBR(d.data_limite_pedido)}</div>
                  </button>
                ))}
                {!demandas.some(d => ["pendente", "em_cotacao"].includes(d.status)) && <p className="py-8 text-center text-sm text-muted-foreground">Nenhuma solicitacao aberta.</p>}
              </CardContent>
            </Card>
            <QuoteWorkbench demanda={quoteDemand} fornecedores={fornecedores} historico={historico} onDone={carregar} />
          </div>
        </TabsContent>

        <TabsContent value="pedidos">
          <Card>
            <CardContent className="p-0">
              <POsTable pos={pos} nav={nav} onEtiqueta={setLabelPO} />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="precos">
          <PriceHistory historico={historico} nav={nav} />
        </TabsContent>

        <TabsContent value="fornecedores">
          <SupplierAnalysis fornecedores={fornecedores} pos={pos} historico={historico} nav={nav} />
        </TabsContent>
      </Tabs>

      <NewDemandDialog open={requestOpen} onClose={() => setRequestOpen(false)} itens={itens} fornecedores={fornecedores} onCreated={carregar} />
      <EtiquetaDialog po={labelPO} onClose={() => setLabelPO(null)} />
    </div>
  );
}

function FlowStrip({ nav }) {
  const steps = [
    ["Solicitacao", "Demanda manual ou MRP", ClipboardList, "/compras"],
    ["Cotacao", "Preco, prazo e condicoes", Handshake, "/compras/itens"],
    ["PO", "Vencedor vira pedido", ShoppingCart, "/compras/pos"],
    ["Recebimento", "Entrada e CQ/WMS", Truck, "/recebimento"],
  ];
  return (
    <Card>
      <CardContent className="grid gap-2 p-4 md:grid-cols-[1fr_auto_1fr_auto_1fr_auto_1fr] md:items-center">
        {steps.map(([title, desc, Icon, href], index) => (
          <div key={title} className="contents">
            <button onClick={() => nav(href)} className="rounded-lg border bg-card p-4 text-left transition hover:bg-muted/40">
              <Icon className="mb-3 h-5 w-5 text-primary" />
              <p className="font-semibold">{title}</p>
              <p className="mt-1 text-xs text-muted-foreground">{desc}</p>
            </button>
            {index < 3 && <ChevronRight className="hidden h-4 w-4 text-muted-foreground md:block" />}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function DemandasTable({ rows, selected, toggle, openQuote, nav }) {
  if (!rows.length) return <Empty text="Nenhuma solicitacao encontrada." />;
  return (
    <>
      <div className="hidden overflow-x-auto md:block">
        <table className="w-full min-w-[980px] text-sm">
          <thead className="border-b bg-muted/40 text-left text-[11px] uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="w-10 p-3" />
              <th className="p-3">Numero</th>
              <th className="p-3">Material</th>
              <th className="p-3 text-right">Qtd</th>
              <th className="p-3">Limite</th>
              <th className="p-3">Motivo</th>
              <th className="p-3">Fornecedor pref.</th>
              <th className="p-3">Status</th>
              <th className="p-3 text-right">Acoes</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((d) => (
              <tr key={d.id} className="border-b hover:bg-accent/40">
                <td className="p-3">
                  <input type="checkbox" checked={selected.includes(d.id)} disabled={d.status === "po_emitida"} onChange={() => toggle(d.id)} />
                </td>
                <td className="p-3 font-mono text-xs font-bold text-primary">{d.numero_solicitacao || d.mrp_numero || d.id.slice(0, 8)}</td>
                <td className="p-3">
                  <div className="font-semibold">{d.item_descricao}</div>
                  <div className="font-mono text-xs text-muted-foreground">{d.item_codigo || d.item_id}</div>
                </td>
                <td className="p-3 text-right font-semibold">{fmt(d.quantidade)} {d.unidade_compra || ""}</td>
                <td className={`p-3 ${d.urgente ? "font-semibold text-red-600" : "text-muted-foreground"}`}>{dateBR(d.data_limite_pedido)}</td>
                <td className="p-3 text-muted-foreground">{d.motivo || "-"}</td>
                <td className="p-3 text-muted-foreground">{d.fornecedor_selecionado_nome || d.fornecedor_selecionado_id || "-"}</td>
                <td className="p-3">{statusBadge(d.status)}</td>
                <td className="p-3 text-right">
                  <div className="flex justify-end gap-2">
                    <Button size="sm" variant="outline" onClick={() => openQuote(d)} disabled={d.status === "po_emitida"}>Cotar</Button>
                    <Button size="sm" variant="ghost" onClick={() => nav(`/compras/cotacao/${d.id}`)}>Detalhe</Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="space-y-3 md:hidden">
        {rows.map((d) => (
          <Card key={d.id}>
            <CardContent className="space-y-3 p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="font-mono text-xs font-bold text-primary">{d.numero_solicitacao || d.mrp_numero || d.id.slice(0, 8)}</div>
                  <div className="truncate font-semibold">{d.item_descricao}</div>
                  <div className="text-xs text-muted-foreground">{fmt(d.quantidade)} {d.unidade_compra || ""}</div>
                </div>
                {statusBadge(d.status)}
              </div>
              <Button size="sm" className="w-full" onClick={() => openQuote(d)} disabled={d.status === "po_emitida"}>Cotar</Button>
            </CardContent>
          </Card>
        ))}
      </div>
    </>
  );
}

function QuoteWorkbench({ demanda, fornecedores, historico, onDone }) {
  const nav = useNavigate();
  const [form, setForm] = useState({ fornecedor_id: "", preco_unitario: "", prazo_pagamento_texto: "30 DDL", prazo_pagamento_dias: 30, prazo_entrega_dias_uteis: 7, moq: 1, frete_tipo: "cif", frete_valor: 0, valido_ate: "" });
  const [saving, setSaving] = useState(false);
  const [creatingPO, setCreatingPO] = useState(false);

  useEffect(() => {
    setForm({ fornecedor_id: demanda?.fornecedor_selecionado_id || "", preco_unitario: "", prazo_pagamento_texto: "30 DDL", prazo_pagamento_dias: 30, prazo_entrega_dias_uteis: 7, moq: 1, frete_tipo: "cif", frete_valor: 0, valido_ate: "" });
  }, [demanda?.id, demanda?.fornecedor_selecionado_id]);

  const itemHistory = useMemo(() => {
    if (!demanda?.item_id) return [];
    return historico.filter(h => h.item_id === demanda.item_id);
  }, [historico, demanda?.item_id]);

  const latestBySupplier = useMemo(() => {
    const map = new Map();
    for (const h of itemHistory) {
      if (!map.has(h.fornecedor_id)) map.set(h.fornecedor_id, h);
    }
    return Array.from(map.values()).sort((a, b) => Number(a.preco_unitario || Infinity) - Number(b.preco_unitario || Infinity));
  }, [itemHistory]);

  if (!demanda) {
    return (
      <Card>
        <CardContent className="py-16 text-center">
          <Handshake className="mx-auto mb-4 h-12 w-12 text-muted-foreground/30" />
          <p className="font-medium">Selecione uma solicitacao para cotar.</p>
          <p className="mt-1 text-sm text-muted-foreground">O comparativo multi-fornecedor aparece aqui.</p>
        </CardContent>
      </Card>
    );
  }

  const set = (key, value) => setForm((current) => ({ ...current, [key]: value }));

  const applyQuote = (quote) => {
    setForm({
      fornecedor_id: quote.fornecedor_id,
      preco_unitario: quote.preco_unitario,
      prazo_pagamento_texto: quote.prazo_pagamento_texto || "30 DDL",
      prazo_pagamento_dias: quote.prazo_pagamento_dias || 30,
      prazo_entrega_dias_uteis: quote.prazo_entrega_dias_uteis || 7,
      moq: quote.moq || 1,
      frete_tipo: quote.frete_tipo || "cif",
      frete_valor: quote.frete_valor || 0,
      valido_ate: quote.valido_ate || "",
      condicao_comercial_id: quote.id,
    });
  };

  const registrar = async () => {
    if (!form.fornecedor_id || !form.preco_unitario) {
      toast.error("Fornecedor e preco sao obrigatorios");
      return;
    }
    setSaving(true);
    try {
      const { data } = await api.post(`/compras/itens/${demanda.item_id}/cotar`, {
        ...form,
        preco_unitario: Number(form.preco_unitario),
        prazo_pagamento_dias: Number(form.prazo_pagamento_dias),
        prazo_entrega_dias_uteis: Number(form.prazo_entrega_dias_uteis),
        moq: Number(form.moq),
        frete_valor: Number(form.frete_valor || 0),
      });
      await api.put(`/compras/demandas/${demanda.id}`, {
        status: "em_cotacao",
        fornecedor_selecionado_id: form.fornecedor_id,
      }).catch(() => null);
      setForm((current) => ({ ...current, condicao_comercial_id: data.id }));
      toast.success("Cotacao registrada");
      onDone();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Erro ao registrar cotacao");
    } finally {
      setSaving(false);
    }
  };

  const gerarPO = async () => {
    if (!form.fornecedor_id || !form.preco_unitario) {
      toast.error("Selecione uma cotacao vencedora antes de gerar a PO");
      return;
    }
    setCreatingPO(true);
    try {
      const { data } = await api.post("/compras/pos", {
        fornecedor_id: form.fornecedor_id,
        origem: "cotacao",
        prazo_pagamento_texto: form.prazo_pagamento_texto,
        prazo_pagamento_dias: Number(form.prazo_pagamento_dias),
        data_entrega_solicitada: demanda.data_limite_pedido,
        demanda_ids: [demanda.id],
        itens: [{
          item_id: demanda.item_id,
          item_descricao: demanda.item_descricao,
          quantidade_solicitada: Number(demanda.quantidade || 1),
          unidade_compra: demanda.unidade_compra || "un",
          preco_unitario: Number(form.preco_unitario),
          frete_rateado: Number(form.frete_valor || 0),
          condicao_comercial_id: form.condicao_comercial_id,
        }],
      });
      toast.success("PO criada a partir da cotacao vencedora");
      onDone();
      nav(`/compras/pos/${data.id}`);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Erro ao gerar PO");
    } finally {
      setCreatingPO(false);
    }
  };

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex flex-wrap items-center justify-between gap-2 text-sm">
          <span>{demanda.item_descricao}</span>
          <Badge variant="outline">{fmt(demanda.quantidade)} {demanda.unidade_compra || ""}</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 lg:grid-cols-3">
          {latestBySupplier.map((quote, index) => (
            <button key={quote.id} onClick={() => applyQuote(quote)} className={`rounded-lg border p-3 text-left transition hover:border-primary/40 ${form.condicao_comercial_id === quote.id ? "border-primary bg-primary/5" : "bg-card"}`}>
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold">{quote.fornecedor_nome}</div>
                  <div className="text-xs text-muted-foreground">{quote.fornecedor_codigo || quote.status_homologacao || "Fornecedor"}</div>
                </div>
                {index === 0 && <Badge className="bg-green-100 text-green-700 dark:bg-green-950/30 dark:text-green-300">Melhor</Badge>}
              </div>
              <div className="mt-3 text-xl font-bold">{fmtBRL(quote.preco_unitario)}</div>
              <div className="mt-1 text-xs text-muted-foreground">{quote.prazo_entrega_dias_uteis || "-"} dias - MOQ {quote.moq || "-"}</div>
            </button>
          ))}
          {!latestBySupplier.length && (
            <div className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground lg:col-span-3">
              Nenhuma cotacao anterior para este item.
            </div>
          )}
        </div>

        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <Field label="Fornecedor">
            <Select value={form.fornecedor_id} onValueChange={(v) => set("fornecedor_id", v)}>
              <SelectTrigger><SelectValue placeholder="Selecionar..." /></SelectTrigger>
              <SelectContent>{fornecedores.map(f => <SelectItem key={f.id} value={f.id}>{f.codigo_interno} - {f.razao_social}</SelectItem>)}</SelectContent>
            </Select>
          </Field>
          <Field label="Preco unitario">
            <Input type="number" min="0" step="0.0001" value={form.preco_unitario} onChange={(e) => set("preco_unitario", e.target.value)} />
          </Field>
          <Field label="Prazo pagamento">
            <Input value={form.prazo_pagamento_texto} onChange={(e) => set("prazo_pagamento_texto", e.target.value)} />
          </Field>
          <Field label="Entrega dias uteis">
            <Input type="number" value={form.prazo_entrega_dias_uteis} onChange={(e) => set("prazo_entrega_dias_uteis", e.target.value)} />
          </Field>
          <Field label="MOQ">
            <Input type="number" value={form.moq} onChange={(e) => set("moq", e.target.value)} />
          </Field>
          <Field label="Frete">
            <Select value={form.frete_tipo} onValueChange={(v) => set("frete_tipo", v)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>{FRETES.map(f => <SelectItem key={f} value={f}>{f.toUpperCase()}</SelectItem>)}</SelectContent>
            </Select>
          </Field>
          <Field label="Valor frete">
            <Input type="number" value={form.frete_valor} onChange={(e) => set("frete_valor", e.target.value)} />
          </Field>
          <Field label="Valida ate">
            <Input type="date" value={form.valido_ate} onChange={(e) => set("valido_ate", e.target.value)} />
          </Field>
        </div>

        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="outline" onClick={registrar} disabled={saving}>
            {saving ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Plus className="mr-1 h-4 w-4" />}
            Registrar cotacao
          </Button>
          <Button onClick={gerarPO} disabled={creatingPO}>
            {creatingPO ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <ShoppingCart className="mr-1 h-4 w-4" />}
            Gerar PO do vencedor
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function POsTable({ pos, nav, onEtiqueta }) {
  if (!pos.length) return <Empty text="Nenhum pedido de compra encontrado." />;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[900px] text-sm">
        <thead className="border-b bg-muted/40 text-left text-[11px] uppercase tracking-wide text-muted-foreground">
          <tr>
            <th className="p-3">Numero</th>
            <th className="p-3">Fornecedor</th>
            <th className="p-3">Itens</th>
            <th className="p-3 text-right">Valor</th>
            <th className="p-3">Entrega</th>
            <th className="p-3">Status</th>
            <th className="p-3 text-right">Acoes</th>
          </tr>
        </thead>
        <tbody>
          {pos.map((po) => (
            <tr key={po.id} className={`border-b hover:bg-accent/40 ${po.urgente ? "bg-red-50/40 dark:bg-red-950/10" : ""}`}>
              <td className="p-3 font-mono text-xs font-bold text-primary">{po.numero_po || "(rascunho)"}</td>
              <td className="p-3 font-medium">{po.fornecedor_nome}</td>
              <td className="p-3 text-xs text-muted-foreground">{(po.itens || []).map(i => i.item_descricao).join(" | ")}</td>
              <td className="p-3 text-right font-semibold">{fmtBRL(po.valor_total_po)}</td>
              <td className="p-3">{dateBR(po.data_entrega_confirmada || po.data_entrega_solicitada)}</td>
              <td className="p-3">{poBadge(po.status)}</td>
              <td className="p-3">
                <div className="flex justify-end gap-2">
                  <Button size="sm" variant="outline" onClick={() => onEtiqueta(po)}><Tag className="mr-1 h-3.5 w-3.5" /> Etiqueta</Button>
                  <Button size="sm" variant="ghost" onClick={() => nav(`/compras/pos/${po.id}`)}>Abrir</Button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PriceHistory({ historico, nav }) {
  const [q, setQ] = useState("");
  const rows = historico.filter(h => !q || normalize(`${h.item_codigo} ${h.item_descricao} ${h.fornecedor_nome}`).includes(normalize(q)));
  return (
    <Card>
      <CardContent className="space-y-4 p-4">
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Buscar material ou fornecedor..." />
        {!rows.length ? <Empty text="Nenhum historico de preco encontrado." /> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] text-sm">
              <thead className="border-b bg-muted/40 text-left text-[11px] uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="p-3">Data</th>
                  <th className="p-3">Material</th>
                  <th className="p-3">Fornecedor</th>
                  <th className="p-3 text-right">Preco</th>
                  <th className="p-3">Prazo</th>
                  <th className="p-3">Condicao</th>
                  <th className="p-3">Homologacao</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((h) => {
                  const best = Number(h.preco_unitario) === Number(h.menor_preco_item);
                  return (
                    <tr key={h.id} className="border-b hover:bg-accent/40" onClick={() => nav(`/compras/itens/${h.item_id}`)}>
                      <td className="p-3 text-muted-foreground">{dateBR(h.created_at)}</td>
                      <td className="p-3">
                        <div className="font-semibold">{h.item_descricao}</div>
                        <div className="font-mono text-xs text-muted-foreground">{h.item_codigo}</div>
                      </td>
                      <td className="p-3">{h.fornecedor_nome}</td>
                      <td className="p-3 text-right font-semibold">
                        {best && <Badge className="mr-2 bg-green-100 text-green-700 dark:bg-green-950/30 dark:text-green-300">menor</Badge>}
                        {fmtBRL(h.preco_unitario)}
                      </td>
                      <td className="p-3">{h.prazo_entrega_dias_uteis || "-"} dias</td>
                      <td className="p-3">{h.prazo_pagamento_texto || "-"}</td>
                      <td className="p-3">{h.status_homologacao || "-"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function SupplierAnalysis({ fornecedores, pos, historico, nav }) {
  const rows = fornecedores.map((f) => {
    const fornecedorPos = pos.filter(p => p.fornecedor_id === f.id);
    const fornecedorHist = historico.filter(h => h.fornecedor_id === f.id);
    return {
      ...f,
      poCount: fornecedorPos.length,
      total: fornecedorPos.reduce((s, p) => s + Number(p.valor_total_po || 0), 0),
      cotacoes: fornecedorHist.length,
      menorPrecoCount: fornecedorHist.filter(h => Number(h.preco_unitario) === Number(h.menor_preco_item)).length,
    };
  }).sort((a, b) => b.total - a.total || b.cotacoes - a.cotacoes);
  return (
    <Card>
      <CardContent className="grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-3">
        {rows.map((f) => (
          <button key={f.id} onClick={() => nav(`/compras/fornecedores/${f.id}`)} className="rounded-lg border bg-card p-4 text-left transition hover:border-primary/40">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="truncate font-semibold">{f.razao_social}</div>
                <div className="text-xs text-muted-foreground">{f.codigo_interno} - {(f.homologacao || {}).status || "sem homologacao"}</div>
              </div>
              <ChevronRight className="h-4 w-4 text-muted-foreground" />
            </div>
            <div className="mt-4 grid grid-cols-3 gap-2 text-center">
              <MiniMetric label="POs" value={f.poCount} />
              <MiniMetric label="Cotacoes" value={f.cotacoes} />
              <MiniMetric label="Melhor" value={f.menorPrecoCount} />
            </div>
            <div className="mt-3 text-sm font-semibold">{fmtBRL(f.total)}</div>
          </button>
        ))}
        {!rows.length && <div className="md:col-span-2 xl:col-span-3"><Empty text="Nenhum fornecedor encontrado." /></div>}
      </CardContent>
    </Card>
  );
}

function NewDemandDialog({ open, onClose, itens, fornecedores, onCreated }) {
  const [form, setForm] = useState({ item_id: "", quantidade: "", data_limite_pedido: "", motivo: "", fornecedor_selecionado_id: "", observacoes: "" });
  const [saving, setSaving] = useState(false);
  const set = (key, value) => setForm((current) => ({ ...current, [key]: value }));
  const salvar = async () => {
    if (!form.item_id || !form.quantidade) {
      toast.error("Item e quantidade sao obrigatorios");
      return;
    }
    setSaving(true);
    try {
      await api.post("/compras/demandas", {
        ...form,
        quantidade: Number(form.quantidade),
        fornecedor_selecionado_id: form.fornecedor_selecionado_id || null,
      });
      toast.success("Solicitacao criada");
      onCreated();
      onClose();
      setForm({ item_id: "", quantidade: "", data_limite_pedido: "", motivo: "", fornecedor_selecionado_id: "", observacoes: "" });
    } catch (err) {
      toast.error(err.response?.data?.detail || "Erro ao criar solicitacao");
    } finally {
      setSaving(false);
    }
  };
  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader><DialogTitle>Nova Solicitacao de Compra</DialogTitle></DialogHeader>
        <div className="grid gap-3 md:grid-cols-2">
          <Field label="Item">
            <Select value={form.item_id} onValueChange={(v) => set("item_id", v)}>
              <SelectTrigger><SelectValue placeholder="Selecionar item..." /></SelectTrigger>
              <SelectContent>{itens.map(i => <SelectItem key={i.id} value={i.id}>{i.codigo_interno} - {i.descricao}</SelectItem>)}</SelectContent>
            </Select>
          </Field>
          <Field label="Quantidade">
            <Input type="number" min="0" step="0.001" value={form.quantidade} onChange={(e) => set("quantidade", e.target.value)} />
          </Field>
          <Field label="Data limite">
            <Input type="date" value={form.data_limite_pedido} onChange={(e) => set("data_limite_pedido", e.target.value)} />
          </Field>
          <Field label="Fornecedor preferencial">
            <Select value={form.fornecedor_selecionado_id || "none"} onValueChange={(v) => set("fornecedor_selecionado_id", v === "none" ? "" : v)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="none">Sem preferencial</SelectItem>
                {fornecedores.map(f => <SelectItem key={f.id} value={f.id}>{f.codigo_interno} - {f.razao_social}</SelectItem>)}
              </SelectContent>
            </Select>
          </Field>
          <Field label="Motivo">
            <Input value={form.motivo} onChange={(e) => set("motivo", e.target.value)} placeholder="reposicao, OP, urgencia..." />
          </Field>
          <Field label="Observacoes" className="md:col-span-2">
            <Textarea value={form.observacoes} onChange={(e) => set("observacoes", e.target.value)} />
          </Field>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancelar</Button>
          <Button onClick={salvar} disabled={saving}>{saving && <Loader2 className="mr-1 h-4 w-4 animate-spin" />} Criar solicitacao</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function EtiquetaDialog({ po, onClose }) {
  if (!po) return null;
  const etiqueta = [
    `Fornecedor: ${po.fornecedor_nome || "-"}`,
    `Pedido de Compra: ${po.numero_po || po.id}`,
    `Entrega solicitada: ${po.data_entrega_confirmada || po.data_entrega_solicitada || "-"}`,
    `Itens: ${(po.itens || []).map(i => `${i.item_descricao} - ${fmt(i.quantidade_solicitada)} ${i.unidade_compra}`).join(" | ")}`,
    "Identificar cada volume com numero da PO, item, lote do fornecedor, quantidade e NF.",
  ].join("\n");
  const copiar = async () => {
    try {
      await navigator.clipboard.writeText(etiqueta);
      toast.success("Padrao de etiqueta copiado");
    } catch {
      toast.error("Nao foi possivel copiar");
    }
  };
  return (
    <Dialog open={!!po} onOpenChange={(v) => !v && onClose()}>
      <DialogContent>
        <DialogHeader><DialogTitle className="flex items-center gap-2"><Tag className="h-5 w-5" /> Padrao de envio ao fornecedor</DialogTitle></DialogHeader>
        <pre className="whitespace-pre-wrap rounded-lg border bg-muted/40 p-4 text-sm">{etiqueta}</pre>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Fechar</Button>
          <Button variant="outline" onClick={copiar}><Copy className="mr-1 h-4 w-4" /> Copiar</Button>
          <Button onClick={() => window.open(`/api/compras/pos/${po.id}/pdf`, "_blank")}><FileText className="mr-1 h-4 w-4" /> PDF</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function MetricCard({ title, value, icon: Icon, tone, text }) {
  const tones = {
    amber: "border-amber-200 bg-amber-50/70 dark:bg-amber-950/10",
    blue: "border-blue-200 bg-blue-50/70 dark:bg-blue-950/10",
    indigo: "border-indigo-200 bg-indigo-50/70 dark:bg-indigo-950/10",
    red: "border-red-200 bg-red-50/70 dark:bg-red-950/10",
    green: "border-green-200 bg-green-50/70 dark:bg-green-950/10",
    neutral: "border-border bg-card",
  };
  return (
    <Card className={tones[tone] || tones.neutral}>
      <CardContent className="p-4">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate text-xs text-muted-foreground">{title}</p>
            <p className={`mt-1 truncate font-bold ${text ? "text-base" : "text-2xl"}`}>{value}</p>
          </div>
          <Icon className="h-5 w-5 shrink-0 text-muted-foreground" />
        </div>
      </CardContent>
    </Card>
  );
}

function MiniMetric({ label, value }) {
  return (
    <div className="rounded-md bg-muted/50 p-2">
      <div className="text-sm font-bold">{value}</div>
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
    </div>
  );
}

function Field({ label, children, className = "" }) {
  return (
    <div className={`space-y-1 ${className}`}>
      <Label className="text-xs font-medium text-muted-foreground">{label}</Label>
      {children}
    </div>
  );
}

function Loading() {
  return <div className="flex justify-center py-12"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>;
}

function Empty({ text }) {
  return <div className="rounded-lg border border-dashed py-12 text-center text-sm text-muted-foreground">{text}</div>;
}
