import { useState, useEffect, useCallback, useMemo } from "react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import {
  Search, PackageCheck, Plus, Info, BarChart3, TrendingUp, AlertTriangle,
  CheckCircle2, Clock, Loader2, Factory
} from "lucide-react";
import { toast } from "sonner";
import { CurrencyInput, fmtCurrency } from "@/components/ui/CurrencyInput";

const STATUS_COLORS = {
  ativo: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300",
  suspenso: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
  descontinuado: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300",
};

function fmtNum(v, decimals = 1) {
  if (v === null || v === undefined) return "—";
  return Number(v).toLocaleString("pt-BR", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

function UNHCard({ label, value, selected, onSelect, highlight }) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`rounded-xl border p-3 text-left w-full transition-all ${
        selected
          ? "border-primary bg-primary/5 ring-1 ring-primary"
          : highlight
          ? "border-blue-300 bg-blue-50 dark:bg-blue-950/30 dark:border-blue-800"
          : "border-border hover:bg-accent/50"
      }`}
    >
      <p className="text-[10px] text-muted-foreground uppercase tracking-wide mb-0.5">{label}</p>
      <p className={`text-base font-semibold mono-num ${value ? "" : "text-muted-foreground"}`}>
        {value ? `${fmtNum(value)} un/h` : "—"}
      </p>
    </button>
  );
}

function SaldoStatusBadge({ op }) {
  const cfg = {
    aberta:      { label: "Programada",   cls: "bg-blue-100 text-blue-700" },
    em_processo: { label: "Em produção",  cls: "bg-amber-100 text-amber-700" },
    pausada:     { label: "Pausada",      cls: "bg-orange-100 text-orange-700" },
    concluida:   { label: "Concluída",    cls: "bg-green-100 text-green-700" },
    cancelada:   { label: "Cancelada",    cls: "bg-red-100 text-red-700" },
  }[op.status] || { label: op.status, cls: "bg-slate-100 text-slate-700" };
  return <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${cfg.cls}`}>{cfg.label}</span>;
}

export default function SKUsPage() {
  const [skus, setSkus] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [filterStatus, setFilterStatus] = useState("all");
  const [filterCat, setFilterCat] = useState("all");
  const [selectedSku, setSelectedSku] = useState(null);
  const [tab, setTab] = useState("info");
  const [showCatRef, setShowCatRef] = useState(false);

  // Dialogs
  const [showAddOrder, setShowAddOrder] = useState(false);
  const [showDescontinuar, setShowDescontinuar] = useState(false);
  const [newOrder, setNewOrder] = useState({ data_pedido: "", quantidade: 0, valor_total: 0, observacao: "" });
  const [motivoDesc, setMotivoDesc] = useState("");

  // Produção state
  const [metaForm, setMetaForm] = useState({ meta_unh: "", ajuste_percentual: "" });
  const [selectedMetrica, setSelectedMetrica] = useState(null); // "geral"|"12m"|"3m"|"1m"|"meta"
  const [savingMeta, setSavingMeta] = useState(false);

  // Saldo state
  const [saldo, setSaldo] = useState(null);
  const [loadingSaldo, setLoadingSaldo] = useState(false);

  // Price currency state for SKU detail sheet
  const [skuPriceVal, setSkuPriceVal] = useState("");
  const [skuPriceCurrency, setSkuPriceCurrency] = useState("BRL");

  useEffect(() => {
    if (selectedSku) {
      setSkuPriceVal(selectedSku.preco_unitario ?? "");
      setSkuPriceCurrency(selectedSku.preco_unitario_currency || "BRL");
    }
  }, [selectedSku]);

  const skuCategoryOptions = useMemo(() => {
    const entries = skus
      .map((sku) => {
        const code = sku.cat3 || sku.codigo_interno?.split("-")[0];
        if (!code) return null;
        return [code, { code, label: sku.categoria || code }];
      })
      .filter(Boolean);
    return Array.from(new Map(entries).values()).sort((a, b) => a.code.localeCompare(b.code));
  }, [skus]);

  const loadSkus = useCallback(async () => {
    try {
      const params = {};
      if (search) params.search = search;
      if (filterStatus !== "all") params.status = filterStatus;
      if (filterCat !== "all") params.cat3 = filterCat;
      const { data } = await api.get("/crm/skus", { params });
      setSkus(data);
    } catch {
      toast.error("Erro ao carregar SKUs");
    } finally {
      setLoading(false);
    }
  }, [search, filterStatus, filterCat]);

  useEffect(() => { loadSkus(); }, [loadSkus]);

  const openSku = (sku) => {
    setSelectedSku(sku);
    setTab("info");
    setSelectedMetrica(null);
    setMetaForm({
      meta_unh: sku.medias_producao?.meta_unh ?? "",
      ajuste_percentual: sku.medias_producao?.ajuste_percentual ?? 0,
    });
    setSaldo(null);
  };

  const handleUpdateSku = async (skuId, updates) => {
    try {
      const resp = await api.put(`/crm/skus/${skuId}`, updates);
      toast.success("SKU atualizado!");
      setSelectedSku(resp.data);
      loadSkus();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Erro ao atualizar");
    }
  };

  const handleSaveMeta = async () => {
    if (!selectedSku) return;
    setSavingMeta(true);
    try {
      const body = {};
      if (metaForm.meta_unh !== "") body.meta_unh = parseFloat(metaForm.meta_unh) || 0;
      if (metaForm.ajuste_percentual !== "") body.ajuste_percentual = parseFloat(metaForm.ajuste_percentual) || 0;
      const resp = await api.post(`/crm/skus/${selectedSku.id}/meta`, body);
      toast.success("Meta/ajuste salvo!");
      setSelectedSku(resp.data);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Erro");
    } finally {
      setSavingMeta(false);
    }
  };

  const handleDescontinuar = async () => {
    if (!motivoDesc.trim()) return;
    try {
      const resp = await api.post(`/crm/skus/${selectedSku.id}/descontinuar`, { motivo: motivoDesc });
      toast.success("SKU descontinuado");
      setSelectedSku(resp.data);
      setShowDescontinuar(false);
      setMotivoDesc("");
      loadSkus();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Erro");
    }
  };

  const handleAddOrder = async () => {
    if (!selectedSku || !newOrder.data_pedido || !newOrder.quantidade) return;
    try {
      const resp = await api.post(`/crm/skus/${selectedSku.id}/orders`, newOrder);
      toast.success("Pedido registrado!");
      setSelectedSku(resp.data);
      setShowAddOrder(false);
      setNewOrder({ data_pedido: "", quantidade: 0, valor_total: 0, observacao: "" });
      loadSkus();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Erro");
    }
  };

  const loadSaldo = async () => {
    if (!selectedSku) return;
    setLoadingSaldo(true);
    try {
      const resp = await api.get(`/crm/skus/${selectedSku.id}/saldo`);
      setSaldo(resp.data);
    } catch {
      toast.error("Erro ao carregar saldo");
    } finally {
      setLoadingSaldo(false);
    }
  };

  // Compute adjusted un/h from selected metrica
  const mp = selectedSku?.medias_producao || {};
  const metricaBase = {
    geral: mp.media_geral_unh,
    "12m": mp.media_12m_unh,
    "3m": mp.media_3m_unh,
    "1m": mp.media_1m_unh,
    meta: mp.meta_unh,
  }[selectedMetrica] ?? null;
  const ajuste = mp.ajuste_percentual ?? 0;
  const unh_ajustada = metricaBase !== null ? +(metricaBase * (1 + ajuste / 100)).toFixed(1) : null;

  return (
    <div className="h-full overflow-auto">
      <div className="max-w-7xl mx-auto p-6 space-y-5">
        {/* Header */}
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-2xl font-heading font-semibold tracking-tight flex items-center gap-2">
              <PackageCheck className="h-6 w-6" /> SKUs / Catálogo
            </h1>
            <p className="text-sm text-muted-foreground mt-1">
              {skus.length} SKU(s) · formato <span className="font-mono text-xs">CAT3-CLI4-SEQ4</span> (ex: BSP-ACME-0001)
            </p>
          </div>
          <button
            onClick={() => setShowCatRef(v => !v)}
            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-primary border rounded-lg px-3 py-1.5 hover:bg-accent transition-colors"
          >
            <Info className="h-3.5 w-3.5" /> Tabela de Categorias
          </button>
        </div>

        {/* Category reference panel */}
        {showCatRef && (
          <div className="border rounded-xl p-4 bg-muted/30">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-3">Tabela CAT3</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
              {skuCategoryOptions.map(cat => (
                <div key={cat.code} className="flex gap-2 text-sm p-2 rounded-lg hover:bg-accent/30">
                  <span className="font-mono font-bold text-primary bg-primary/10 px-2 py-0.5 rounded text-xs shrink-0 self-start mt-0.5">{cat.code}</span>
                  <div>
                    <p className="text-xs font-medium">{cat.label}</p>
                    <p className="text-[10px] text-muted-foreground">Código CAT3 ativo encontrado no catálogo.</p>
                  </div>
                </div>
              ))}
              {skuCategoryOptions.length === 0 && (
                <p className="text-sm text-muted-foreground">Nenhum CAT3 encontrado nos SKUs atuais.</p>
              )}
            </div>
          </div>
        )}

        {/* Filters */}
        <div className="flex items-center gap-3 flex-wrap">
          <Select value={filterStatus} onValueChange={setFilterStatus}>
            <SelectTrigger className="w-36"><SelectValue placeholder="Status" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Todos</SelectItem>
              <SelectItem value="ativo">Ativo</SelectItem>
              <SelectItem value="suspenso">Suspenso</SelectItem>
              <SelectItem value="descontinuado">Descontinuado</SelectItem>
            </SelectContent>
          </Select>
          <Select value={filterCat} onValueChange={setFilterCat}>
            <SelectTrigger className="w-40"><SelectValue placeholder="Categoria" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Todas categorias</SelectItem>
              {skuCategoryOptions.map(c => <SelectItem key={c.code} value={c.code}>{c.code} — {c.label}</SelectItem>)}
            </SelectContent>
          </Select>
          <div className="relative flex-1 min-w-[200px]">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input placeholder="Buscar SKU, produto, cliente…" value={search}
              onChange={(e) => setSearch(e.target.value)} className="pl-9" />
          </div>
        </div>

        {/* Table */}
        {loading ? (
          <div className="flex justify-center py-20"><Loader2 className="h-8 w-8 animate-spin text-muted-foreground" /></div>
        ) : skus.length === 0 ? (
          <div className="text-center py-20">
            <PackageCheck className="h-12 w-12 text-muted-foreground mx-auto mb-4" />
            <p className="text-muted-foreground font-medium">Nenhum SKU encontrado.</p>
            <p className="text-sm text-muted-foreground mt-1">SKUs são gerados automaticamente ao aprovar amostras no CRM 3.</p>
          </div>
        ) : (
          <div className="border rounded-xl overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Código</TableHead>
                  <TableHead>Produto</TableHead>
                  <TableHead>Cliente</TableHead>
                  <TableHead>Cat.</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Preço Unit.</TableHead>
                  <TableHead className="text-right">MOQ</TableHead>
                  <TableHead className="text-right hidden md:table-cell">Média Geral</TableHead>
                  <TableHead className="text-right hidden lg:table-cell">Meta</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {skus.map(sku => {
                  const mp2 = sku.medias_producao || {};
                  return (
                    <TableRow key={sku.id} className="cursor-pointer hover:bg-accent/50"
                      onClick={() => openSku(sku)}>
                      <TableCell className="font-mono font-semibold text-primary text-sm">{sku.codigo_interno}</TableCell>
                      <TableCell className="max-w-[220px]">
                        <p className="truncate text-sm">{sku.nome_produto}</p>
                        {(sku.produto_pai_nome || sku.apresentacao?.volume) && (
                          <p className="truncate text-[10px] text-muted-foreground">
                            {sku.produto_pai_nome || "—"}
                            {sku.apresentacao?.volume ? ` · ${sku.apresentacao.volume}${sku.apresentacao.unidade_volume || "ml"}` : ""}
                          </p>
                        )}
                      </TableCell>
                      <TableCell className="text-muted-foreground text-sm">{sku.cliente_nome}</TableCell>
                      <TableCell>
                        <span className="font-mono text-[11px] font-bold text-primary bg-primary/10 px-1.5 py-0.5 rounded">
                          {sku.cat3 || sku.codigo_interno?.split("-")[0] || "—"}
                        </span>
                      </TableCell>
                      <TableCell>
                        <span className={`text-[10px] font-semibold px-2 py-0.5 rounded uppercase ${STATUS_COLORS[sku.status] || ""}`}>
                          {sku.status}
                        </span>
                      </TableCell>
                      <TableCell className="text-right mono-num text-sm">
                        {sku.preco_unitario ? fmtCurrency(sku.preco_unitario, sku.preco_unitario_currency || "BRL") : "—"}
                      </TableCell>
                      <TableCell className="text-right mono-num text-sm">{sku.moq || "—"}</TableCell>
                      <TableCell className="text-right mono-num text-sm hidden md:table-cell">
                        {mp2.media_geral_unh ? `${fmtNum(mp2.media_geral_unh)} un/h` : "—"}
                      </TableCell>
                      <TableCell className="text-right mono-num text-sm hidden lg:table-cell">
                        {mp2.meta_unh ? `${fmtNum(mp2.meta_unh)} un/h` : "—"}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </div>

      {/* ─── SKU Detail Sheet ─── */}
      <Sheet open={!!selectedSku} onOpenChange={(v) => { if (!v) { setSelectedSku(null); loadSkus(); } }}>
        <SheetContent className="w-full sm:w-[600px] md:w-[680px] p-0 flex flex-col" side="right">
          {selectedSku && (
            <>
              <SheetHeader className="p-6 pb-3 shrink-0">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <SheetTitle className="font-heading text-xl flex items-center gap-2">
                      <PackageCheck className="h-5 w-5 shrink-0" />
                      <span className="font-mono">{selectedSku.codigo_interno}</span>
                    </SheetTitle>
                    <p className="text-sm text-muted-foreground mt-0.5 truncate">{selectedSku.nome_produto}</p>
                    <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                      <Badge variant="outline" className="text-xs">{selectedSku.cliente_nome}</Badge>
                      {selectedSku.categoria && <Badge variant="outline" className="text-xs">{selectedSku.categoria}</Badge>}
                      {selectedSku.produto_pai_nome && (
                        <Badge variant="secondary" className="text-xs">Família: {selectedSku.produto_pai_nome}</Badge>
                      )}
                      {selectedSku.apresentacao?.volume && (
                        <Badge variant="secondary" className="text-xs">
                          {selectedSku.apresentacao.volume}{selectedSku.apresentacao.unidade_volume || "ml"}
                        </Badge>
                      )}
                      <span className={`text-[10px] font-semibold px-2 py-0.5 rounded uppercase ${STATUS_COLORS[selectedSku.status] || ""}`}>
                        {selectedSku.status}
                      </span>
                    </div>
                  </div>
                  {selectedSku.status !== "descontinuado" && (
                    <Button size="sm" variant="ghost" className="text-red-600 hover:bg-red-50 shrink-0 text-xs"
                      onClick={() => setShowDescontinuar(true)}>
                      Descontinuar
                    </Button>
                  )}
                </div>
                {selectedSku.descontinuado_motivo && (
                  <div className="mt-2 rounded-lg border border-red-200 bg-red-50 dark:bg-red-950/20 p-2 text-xs text-red-700">
                    <strong>Motivo:</strong> {selectedSku.descontinuado_motivo}
                    {selectedSku.descontinuado_em && ` · ${new Date(selectedSku.descontinuado_em).toLocaleDateString("pt-BR")}`}
                    {selectedSku.descontinuado_por && ` por ${selectedSku.descontinuado_por}`}
                  </div>
                )}
              </SheetHeader>
              <Separator />

              <Tabs value={tab} onValueChange={(v) => { setTab(v); if (v === "saldo" && !saldo) loadSaldo(); }}
                className="flex-1 flex flex-col min-h-0">
                <TabsList className="mx-6 mt-3 shrink-0">
                  <TabsTrigger value="info">Dados</TabsTrigger>
                  <TabsTrigger value="producao">Produção</TabsTrigger>
                  <TabsTrigger value="saldo">Saldo Aberto</TabsTrigger>
                  <TabsTrigger value="pedidos">Pedidos ({(selectedSku.historico_pedidos || []).length})</TabsTrigger>
                </TabsList>

                {/* ── TAB: Dados ── */}
                <TabsContent value="info" className="flex-1 min-h-0 overflow-y-auto px-6 pb-6 mt-3 space-y-4">
                  <div className="space-y-1">
                    <Label className="text-xs text-muted-foreground">Nome do Produto</Label>
                    <Input defaultValue={selectedSku.nome_produto || ""}
                      onBlur={(e) => handleUpdateSku(selectedSku.id, { nome_produto: e.target.value })} />
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1">
                      <Label className="text-xs text-muted-foreground">Preço Unitário</Label>
                      <CurrencyInput
                        value={skuPriceVal}
                        currency={skuPriceCurrency}
                        onValueChange={setSkuPriceVal}
                        onCurrencyChange={(c) => {
                          setSkuPriceCurrency(c);
                          handleUpdateSku(selectedSku.id, { preco_unitario_currency: c });
                        }}
                        onBlur={() => handleUpdateSku(selectedSku.id, { preco_unitario: parseFloat(skuPriceVal) || 0 })}
                        size="sm"
                      />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-xs text-muted-foreground">MOQ</Label>
                      <Input type="number" defaultValue={selectedSku.moq || 0}
                        onBlur={(e) => handleUpdateSku(selectedSku.id, { moq: parseInt(e.target.value) || 0 })} />
                    </div>
                  </div>
                  {selectedSku.status !== "descontinuado" && (
                    <div className="space-y-1">
                      <Label className="text-xs text-muted-foreground">Status</Label>
                      <Select defaultValue={selectedSku.status}
                        onValueChange={(v) => { if (v === "descontinuado") { setShowDescontinuar(true); } else { handleUpdateSku(selectedSku.id, { status: v }); } }}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="ativo">Ativo</SelectItem>
                          <SelectItem value="suspenso">Suspenso</SelectItem>
                          <SelectItem value="descontinuado">Descontinuado…</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  )}
                  <Separator />
                  <div>
                    <p className="text-xs text-muted-foreground mb-1.5">Código gerado</p>
                    <div className="flex items-center gap-2 font-mono text-sm flex-wrap">
                      <span className="bg-primary/10 text-primary px-2 py-0.5 rounded font-bold">{selectedSku.cat3 || "???"}</span>
                      <span className="text-muted-foreground">-</span>
                      <span className="bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300 px-2 py-0.5 rounded font-bold">{selectedSku.cli4 || "????"}</span>
                      <span className="text-muted-foreground">-</span>
                      <span className="bg-muted px-2 py-0.5 rounded text-muted-foreground">{selectedSku.codigo_interno?.split("-")[2] || "????"}</span>
                      <span className="text-[10px] text-muted-foreground ml-1">= {selectedSku.codigo_interno}</span>
                    </div>
                    <p className="text-[10px] text-muted-foreground mt-1">CAT3 · CLI4 · SEQ4 — imutável após geração</p>
                  </div>
                  <Separator />
                  <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">ANVISA</h4>
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1">
                      <Label className="text-xs text-muted-foreground">Número</Label>
                      <Input defaultValue={selectedSku.anvisa?.numero || ""}
                        onBlur={(e) => handleUpdateSku(selectedSku.id, { anvisa_numero: e.target.value })} />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-xs text-muted-foreground">Validade</Label>
                      <Input type="date"
                        defaultValue={selectedSku.anvisa?.validade ? selectedSku.anvisa.validade.split("T")[0] : ""}
                        onBlur={(e) => handleUpdateSku(selectedSku.id, { anvisa_validade: e.target.value ? e.target.value + "T00:00:00+00:00" : null })} />
                    </div>
                  </div>
                  <Separator />
                  <div className="grid grid-cols-2 gap-3">
                    <div className="bg-muted/40 rounded-lg p-3">
                      <p className="text-xs text-muted-foreground">Último Pedido</p>
                      <p className="font-medium text-sm mono-num">
                        {selectedSku.data_ultimo_pedido ? new Date(selectedSku.data_ultimo_pedido).toLocaleDateString("pt-BR") : "—"}
                      </p>
                    </div>
                    <div className="bg-muted/40 rounded-lg p-3">
                      <p className="text-xs text-muted-foreground">Freq. Recompra</p>
                      <p className="font-medium text-sm mono-num">
                        {selectedSku.frequencia_media_recompra_dias ? `${selectedSku.frequencia_media_recompra_dias} dias` : "—"}
                      </p>
                    </div>
                    <div className="bg-muted/40 rounded-lg p-3">
                      <p className="text-xs text-muted-foreground">Código SKU (imutável)</p>
                      <p className="font-mono font-bold text-sm text-primary">{selectedSku.codigo_interno}</p>
                    </div>
                    <div className="bg-muted/40 rounded-lg p-3">
                      <p className="text-xs text-muted-foreground">Projeto</p>
                      <p className="text-sm truncate">{selectedSku.projeto_nome || "—"}</p>
                    </div>
                  </div>
                </TabsContent>

                {/* ── TAB: Produção (RN-SK-05) ── */}
                <TabsContent value="producao" className="flex-1 min-h-0 overflow-y-auto px-6 pb-6 mt-3 space-y-5">
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <h4 className="text-sm font-semibold flex items-center gap-1.5">
                        <BarChart3 className="h-4 w-4 text-primary" /> Médias de Produção
                      </h4>
                      <p className="text-[10px] text-muted-foreground">Clique numa métrica para calcular estimativa</p>
                    </div>
                    <div className="grid grid-cols-2 gap-2 mb-3">
                      <UNHCard label="Média Geral"    value={mp.media_geral_unh} selected={selectedMetrica === "geral"} onSelect={() => setSelectedMetrica("geral")} />
                      <UNHCard label="Últimos 12 meses" value={mp.media_12m_unh}  selected={selectedMetrica === "12m"}  onSelect={() => setSelectedMetrica("12m")}  />
                      <UNHCard label="Últimos 3 meses"  value={mp.media_3m_unh}   selected={selectedMetrica === "3m"}   onSelect={() => setSelectedMetrica("3m")}   />
                      <UNHCard label="Último mês"       value={mp.media_1m_unh}   selected={selectedMetrica === "1m"}   onSelect={() => setSelectedMetrica("1m")}   />
                    </div>
                    {/* Meta hardcoded */}
                    <UNHCard label="Meta (hardcoded)" value={mp.meta_unh} selected={selectedMetrica === "meta"} onSelect={() => setSelectedMetrica("meta")} highlight />
                    {mp.meta_set_by && (
                      <p className="text-[10px] text-muted-foreground mt-1 ml-1">
                        Definida por {mp.meta_set_by} em {mp.meta_set_at ? new Date(mp.meta_set_at).toLocaleDateString("pt-BR") : "—"}
                      </p>
                    )}
                  </div>

                  {/* Ajuste percentual */}
                  <div className="rounded-xl border p-4 space-y-3">
                    <div className="flex items-center justify-between">
                      <h4 className="text-sm font-semibold flex items-center gap-1.5">
                        <TrendingUp className="h-4 w-4" /> Ajuste Percentual
                      </h4>
                      <span className={`text-sm font-bold mono-num ${(mp.ajuste_percentual || 0) > 0 ? "text-green-600" : (mp.ajuste_percentual || 0) < 0 ? "text-red-600" : "text-muted-foreground"}`}>
                        {(mp.ajuste_percentual || 0) > 0 ? "+" : ""}{mp.ajuste_percentual ?? 0}%
                      </span>
                    </div>
                    <p className="text-xs text-muted-foreground">
                      Positivo = meta mais agressiva. Negativo = buffer de segurança. Aplicado sobre qualquer das 5 médias.
                    </p>
                    <div className="grid grid-cols-2 gap-3">
                      <div className="space-y-1">
                        <Label className="text-xs text-muted-foreground">Meta (un/h)</Label>
                        <Input type="number" step="0.1" value={metaForm.meta_unh}
                          onChange={e => setMetaForm(p => ({ ...p, meta_unh: e.target.value }))}
                          placeholder={mp.meta_unh ? String(mp.meta_unh) : "ex: 9500"} />
                      </div>
                      <div className="space-y-1">
                        <Label className="text-xs text-muted-foreground">Ajuste (%)</Label>
                        <Input type="number" step="1" min="-100" max="100" value={metaForm.ajuste_percentual}
                          onChange={e => setMetaForm(p => ({ ...p, ajuste_percentual: e.target.value }))}
                          placeholder="0" />
                      </div>
                    </div>
                    <Button size="sm" onClick={handleSaveMeta} disabled={savingMeta} className="w-full">
                      {savingMeta ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" /> : null}
                      Salvar Meta / Ajuste
                    </Button>
                  </div>

                  {/* Estimativa interativa */}
                  {selectedMetrica && (
                    <div className="rounded-xl border border-primary/30 bg-primary/5 p-4 space-y-3">
                      <h4 className="text-sm font-semibold">Estimativa de Duração de OP</h4>
                      <EstimativaCalc unh={unh_ajustada} ajuste={ajuste} metricaBase={metricaBase} />
                    </div>
                  )}

                  {/* Histórico de produção */}
                  {(mp.historico_producao || []).length > 0 && (
                    <div>
                      <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
                        Histórico de Produção ({mp.historico_producao.length} OPs)
                      </h4>
                      <div className="space-y-1.5 max-h-48 overflow-y-auto">
                        {[...mp.historico_producao].reverse().map((h, i) => (
                          <div key={i} className="flex items-center justify-between text-xs border rounded-lg px-3 py-1.5">
                            <span className="font-mono text-primary">{h.op_numero}</span>
                            <span className="text-muted-foreground">{h.data ? new Date(h.data).toLocaleDateString("pt-BR") : "—"}</span>
                            <span className="mono-num">{h.qtd_produzida?.toLocaleString("pt-BR")} un</span>
                            <span className="mono-num">{h.duracao_h}h</span>
                            <span className="font-bold text-primary mono-num">{fmtNum(h.unh)} un/h</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </TabsContent>

                {/* ── TAB: Saldo Aberto ── */}
                <TabsContent value="saldo" className="flex-1 min-h-0 overflow-y-auto px-6 pb-6 mt-3 space-y-4">
                  {loadingSaldo ? (
                    <div className="flex justify-center py-12"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
                  ) : !saldo ? (
                    <Button onClick={loadSaldo} variant="outline" className="w-full">Carregar Saldo Aberto</Button>
                  ) : saldo.length === 0 ? (
                    <div className="text-center py-12 text-muted-foreground">
                      <Factory className="h-10 w-10 mx-auto mb-3 opacity-30" />
                      <p className="text-sm">Nenhum pedido com OPs para este SKU.</p>
                    </div>
                  ) : saldo.map((entry, i) => (
                    <Card key={i} className="overflow-hidden">
                      <CardHeader className="pb-2 pt-3 px-4">
                        <div className="flex items-center justify-between gap-2 flex-wrap">
                          <CardTitle className="text-sm font-semibold flex items-center gap-1.5">
                            <span className="font-mono text-primary">#{entry.numero_pedido}</span>
                            <span className="text-muted-foreground font-normal">— {entry.cliente_nome}</span>
                          </CardTitle>
                          <div className="flex items-center gap-2">
                            {entry.saldo_aberto === 0
                              ? <CheckCircle2 className="h-4 w-4 text-green-600" />
                              : !entry.checklist_insumos_ok
                              ? <AlertTriangle className="h-4 w-4 text-amber-500" />
                              : <Clock className="h-4 w-4 text-blue-500" />
                            }
                            <span className={`text-xs font-semibold mono-num ${entry.saldo_aberto === 0 ? "text-green-600" : "text-amber-700"}`}>
                              {entry.saldo_aberto === 0 ? "Saldo: 0 ✅" : `Saldo: ${entry.saldo_aberto.toLocaleString("pt-BR")} un`}
                            </span>
                          </div>
                        </div>
                        <div className="flex items-center gap-3 text-[10px] text-muted-foreground mt-0.5">
                          <span>Pedido: <span className="mono-num font-medium text-foreground">{entry.qtd_pedido?.toLocaleString("pt-BR")} un</span></span>
                          <span>Realizado: <span className="mono-num font-medium text-foreground">{entry.qtd_realizada?.toLocaleString("pt-BR")} un</span></span>
                          {entry.qtd_perda > 0 && <span className="text-red-500">Perda: {entry.qtd_perda?.toLocaleString("pt-BR")} un</span>}
                        </div>
                        {!entry.checklist_insumos_ok && entry.saldo_aberto > 0 && (
                          <p className="text-[10px] text-amber-600 flex items-center gap-1 mt-1">
                            <AlertTriangle className="h-3 w-3" /> Checklist de insumos incompleto — pode travar a produção
                          </p>
                        )}
                      </CardHeader>
                      <CardContent className="px-4 pb-3 space-y-1.5">
                        {(entry.ops || []).map((op, j) => (
                          <div key={j} className="flex items-center gap-3 text-xs border rounded-lg px-3 py-2 bg-muted/20">
                            <span className="font-mono font-semibold text-primary">{op.numero_op}</span>
                            <SaldoStatusBadge op={op} />
                            <span className="text-muted-foreground">{op.qtd_planejada?.toLocaleString("pt-BR")} un plan.</span>
                            {op.qtd_realizada > 0 && <span className="text-green-700 mono-num">{op.qtd_realizada?.toLocaleString("pt-BR")} real.</span>}
                            {op.pcp_data_inicio && (
                              <span className="text-muted-foreground ml-auto">
                                {new Date(op.pcp_data_inicio).toLocaleDateString("pt-BR")}
                                {op.pcp_linha && ` · ${op.pcp_linha}`}
                              </span>
                            )}
                          </div>
                        ))}
                      </CardContent>
                    </Card>
                  ))}
                </TabsContent>

                {/* ── TAB: Pedidos ── */}
                <TabsContent value="pedidos" className="flex-1 min-h-0 overflow-y-auto px-6 pb-6 mt-3 space-y-3">
                  <Button size="sm" onClick={() => { setNewOrder({ data_pedido: "", quantidade: 0, valor_total: 0, observacao: "" }); setShowAddOrder(true); }}>
                    <Plus className="h-3.5 w-3.5 mr-1" /> Registrar Pedido
                  </Button>
                  {(selectedSku.historico_pedidos || []).length === 0 ? (
                    <p className="text-sm text-muted-foreground">Nenhum pedido registrado.</p>
                  ) : (
                    [...(selectedSku.historico_pedidos || [])].reverse().map((order, idx) => (
                      <div key={idx} className="border rounded-lg p-3 space-y-0.5">
                        <div className="flex justify-between items-start">
                          <div>
                            <p className="text-sm font-medium">Qtd: <span className="mono-num">{order.quantidade?.toLocaleString("pt-BR")}</span></p>
                            <p className="text-xs text-muted-foreground mono-num">R$ {order.valor_total?.toFixed(2)}</p>
                          </div>
                          <span className="text-xs text-muted-foreground">
                            {order.data_pedido ? new Date(order.data_pedido).toLocaleDateString("pt-BR") : "—"}
                          </span>
                        </div>
                        {order.observacao && <p className="text-xs text-muted-foreground mt-1">{order.observacao}</p>}
                      </div>
                    ))
                  )}
                </TabsContent>
              </Tabs>
            </>
          )}
        </SheetContent>
      </Sheet>

      {/* ─── Descontinuar Dialog ─── */}
      <Dialog open={showDescontinuar} onOpenChange={setShowDescontinuar}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="font-heading">Descontinuar SKU (RN-SK-03)</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              SKUs nunca são deletados — apenas marcados como descontinuados com motivo obrigatório.
            </p>
            <div className="space-y-1">
              <Label>Motivo *</Label>
              <Textarea value={motivoDesc} onChange={(e) => setMotivoDesc(e.target.value)}
                placeholder="Descreva o motivo da descontinuação…" rows={3} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => { setShowDescontinuar(false); setMotivoDesc(""); }}>Cancelar</Button>
            <Button variant="destructive" onClick={handleDescontinuar} disabled={!motivoDesc.trim()}>Descontinuar</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ─── Add Order Dialog ─── */}
      <Dialog open={showAddOrder} onOpenChange={setShowAddOrder}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="font-heading">Registrar Pedido</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1">
              <Label>Data do Pedido *</Label>
              <Input type="date" value={newOrder.data_pedido}
                onChange={(e) => setNewOrder({ ...newOrder, data_pedido: e.target.value ? e.target.value + "T00:00:00+00:00" : "" })} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label>Quantidade *</Label>
                <Input type="number" value={newOrder.quantidade}
                  onChange={(e) => setNewOrder({ ...newOrder, quantidade: parseInt(e.target.value) || 0 })} />
              </div>
              <div className="space-y-1">
                <Label>Valor Total (R$)</Label>
                <Input type="number" step="0.01" value={newOrder.valor_total}
                  onChange={(e) => setNewOrder({ ...newOrder, valor_total: parseFloat(e.target.value) || 0 })} />
              </div>
            </div>
            <div className="space-y-1">
              <Label>Observação</Label>
              <Input value={newOrder.observacao} onChange={(e) => setNewOrder({ ...newOrder, observacao: e.target.value })} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowAddOrder(false)}>Cancelar</Button>
            <Button onClick={handleAddOrder} disabled={!newOrder.data_pedido || !newOrder.quantidade}>Registrar</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function EstimativaCalc({ unh, ajuste, metricaBase }) {
  const [qtdOp, setQtdOp] = useState("");
  const qtd = parseFloat(qtdOp) || 0;
  const horas = unh && qtd > 0 ? qtd / unh : null;
  return (
    <div className="space-y-3">
      <div className="text-xs text-muted-foreground">
        Base: <span className="font-semibold mono-num">{fmtNum(metricaBase)} un/h</span>
        {ajuste !== 0 && (
          <> · Ajuste: <span className={`font-semibold ${ajuste > 0 ? "text-green-600" : "text-red-600"}`}>{ajuste > 0 ? "+" : ""}{ajuste}%</span>
          {" = "}<span className="font-semibold mono-num text-primary">{fmtNum(unh)} un/h</span></>
        )}
      </div>
      <div className="flex items-center gap-3">
        <div className="flex-1 space-y-1">
          <Label className="text-xs text-muted-foreground">Qtd da OP (unidades)</Label>
          <Input type="number" value={qtdOp} onChange={(e) => setQtdOp(e.target.value)} placeholder="ex: 15000" />
        </div>
        {horas !== null && (
          <div className="text-center shrink-0">
            <p className="text-[10px] text-muted-foreground">Estimativa</p>
            <p className="text-xl font-bold mono-num text-primary">{Math.ceil(horas)}h</p>
            <p className="text-[10px] text-muted-foreground">{fmtNum(horas)} horas exatas</p>
          </div>
        )}
      </div>
    </div>
  );
}
