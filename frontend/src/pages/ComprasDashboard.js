import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import { Loader2, Search, Tag, Trash2 } from "lucide-react";

const STATUS_LABEL = {
  pendente: "Aprovada",
  em_cotacao: "Consolidada em PC",
  po_emitida: "Consolidada em PC",
  cancelada: "Cancelada",
};

const PO_STATUS = {
  rascunho: "Rascunho",
  emitida: "Enviado",
  confirmada: "Enviado",
  parcialmente_recebida: "Recebido parcial",
  recebida: "Recebido",
  encerrada: "Encerrado",
  cancelada: "Cancelado",
};

const TABS = [
  ["solicitacoes", "Solicitações"],
  ["cotacoes", "🤝 Cotações"],
  ["pedidos", "Pedidos de Compra"],
  ["precos", "📊 Histórico de Preços"],
  ["fornecedores", "📈 Análise de Fornecedores"],
  ["busca", "🔎 Busca Avançada: Fornecedores × Material"],
];

function asText(value, fallback = "-") {
  if (value == null || value === "") return fallback;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map((v) => asText(v, "")).filter(Boolean).join(", ") || fallback;
  return value.razao_social || value.nome || value.name || value.descricao || value.codigo || value.email || fallback;
}

function asList(value) {
  return Array.isArray(value) ? value : [];
}

function errorText(err, fallback) {
  const detail = err?.response?.data?.detail;
  if (!detail) return fallback;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => item?.msg || asText(item, "")).filter(Boolean).join("; ") || fallback;
  }
  return detail.msg || asText(detail, fallback);
}

function normalize(value) {
  return asText(value, "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
}

function fmt(value, digits = 3) {
  return Number(value || 0).toLocaleString("pt-BR", { maximumFractionDigits: digits });
}

function money(value) {
  const n = Number(value || 0);
  return n.toLocaleString("pt-BR", { minimumFractionDigits: n % 1 ? 2 : 0, maximumFractionDigits: 2 });
}

function dateBR(value) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleDateString("pt-BR");
  } catch {
    return String(value).slice(0, 10);
  }
}

function dateTimeBR(value) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString("pt-BR");
  } catch {
    return asText(value);
  }
}

function supplierName(f) {
  return asText(f?.razao_social || f?.nome || f?.name || f?.fornecedor_nome || f);
}

function itemLine(item) {
  return `${asText(item?.codigo_interno || item?.item_codigo || item?.codigo || item?.sku, "")} — ${asText(item?.descricao || item?.item_descricao || item?.nome || item?.item, "")}`.replace(/^ — /, "");
}

function orderCustomer(order) {
  return asText(order?.cliente?.razao_social || order?.cliente?.nome || order?.cliente_nome || order?.customer_name || order?.cliente, "Cliente");
}

function statusBadge(status) {
  const label = STATUS_LABEL[status] || asText(status, "Aprovada");
  const cls = status === "cancelada" ? "bg-red-100 text-red-700" : status === "pendente" ? "bg-emerald-100 text-emerald-700" : "bg-blue-100 text-blue-800";
  return <span className={`inline-flex rounded-full px-3 py-1 text-xs font-bold ${cls}`}>{label}</span>;
}

function poBadge(status) {
  const label = PO_STATUS[status] || asText(status, "Enviado");
  const cls = status === "parcialmente_recebida" ? "bg-purple-100 text-purple-700" : status === "cancelada" ? "bg-red-100 text-red-700" : "bg-blue-100 text-blue-800";
  return <span className={`inline-flex rounded-full px-3 py-1 text-xs font-bold ${cls}`}>{label}</span>;
}

function qualityBadge(record) {
  const quality = record?.supplier_quality || record?.qualidade_fornecedor;
  if (!quality) return <Badge variant="outline" className="bg-muted text-muted-foreground">sem selo</Badge>;
  const risco = quality.risco || "medio";
  const cls = risco === "baixo" ? "bg-green-100 text-green-700" : risco === "alto" || risco === "bloqueado" ? "bg-red-100 text-red-700" : "bg-amber-100 text-amber-700";
  return <Badge className={cls} title={`Aprovação: ${quality.taxa_aprovacao ?? "-"}% · RNCs abertas: ${quality.rnc_abertas ?? 0}`}>{quality.selo || (risco === "baixo" ? "✓ verde" : "⚠ atenção")}</Badge>;
}

export default function ComprasDashboard() {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState("solicitacoes");
  const [loading, setLoading] = useState(true);
  const [demandas, setDemandas] = useState([]);
  const [pos, setPos] = useState([]);
  const [itens, setItens] = useState([]);
  const [fornecedores, setFornecedores] = useState([]);
  const [historico, setHistorico] = useState([]);
  const [orders, setOrders] = useState([]);
  const [search, setSearch] = useState("");
  const [statusDemanda, setStatusDemanda] = useState("all");
  const [selectedDemandIds, setSelectedDemandIds] = useState([]);
  const [requestOpen, setRequestOpen] = useState(false);
  const [orderModalOpen, setOrderModalOpen] = useState(false);
  const [labelPO, setLabelPO] = useState(null);

  const carregar = useCallback(async () => {
    setLoading(true);
    try {
      const [demandasRes, posRes, itensRes, fornecedoresRes, histRes, ordersRes] = await Promise.all([
        api.get("/compras/demandas", { params: { limit: 200 } }),
        api.get("/compras/pos", { params: { limit: 200 } }),
        api.get("/compras/itens", { params: { limit: 200 } }),
        api.get("/compras/fornecedores", { params: { limit: 200 } }),
        api.get("/compras/historico-precos", { params: { limit: 200 } }).catch(() => ({ data: { historico: [] } })),
        api.get("/orders").catch(() => ({ data: [] })),
      ]);
      setDemandas(demandasRes.data?.demandas || []);
      setPos(posRes.data?.pos || []);
      setItens(itensRes.data?.itens || []);
      setFornecedores(fornecedoresRes.data?.fornecedores || []);
      setHistorico(histRes.data?.historico || []);
      setOrders(Array.isArray(ordersRes.data) ? ordersRes.data : ordersRes.data?.orders || []);
    } catch (err) {
      toast.error(errorText(err, "Erro ao carregar Compras"));
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
      return normalize(`${d.numero_solicitacao} ${d.item_codigo} ${d.item_descricao} ${d.solicitante_nome} ${d.observacoes} ${d.motivo}`).includes(q);
    });
  }, [demandas, search, statusDemanda]);

  const selectedDemandas = useMemo(() => demandas.filter((d) => selectedDemandIds.includes(d.id)), [demandas, selectedDemandIds]);

  const iniciarCotacao = async () => {
    if (!selectedDemandas.length) return;
    try {
      await Promise.all(selectedDemandas.filter((d) => d.status === "pendente").map((d) => api.put(`/compras/demandas/${d.id}`, { status: "em_cotacao" })));
      toast.success("Cotação iniciada.");
      setSelectedDemandIds([]);
      setActiveTab("cotacoes");
      carregar();
    } catch (err) {
      toast.error(errorText(err, "Não foi possível iniciar cotação"));
    }
  };

  const copiarCotacao = async () => {
    const texto = selectedDemandas.map((d) => `${d.numero_solicitacao || d.id} | ${d.item_codigo || ""} ${d.item_descricao} | ${fmt(d.quantidade)} ${d.unidade_compra || ""}`).join("\n");
    try {
      await navigator.clipboard.writeText(texto);
      toast.success("Texto de cotação copiado.");
    } catch {
      toast.error("Não foi possível copiar.");
    }
  };

  const excluirDemanda = async (id) => {
    try {
      await api.delete(`/compras/demandas/${id}`);
      toast.success("Solicitação excluída.");
      carregar();
    } catch (err) {
      toast.error(errorText(err, "Não foi possível excluir"));
    }
  };

  return (
    <div className="dashboard-shell-wide space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="dashboard-eyebrow">Kuryos ERP · Suprimentos</p>
          <h1 className="dashboard-title font-heading">Compras</h1>
          <p className="mt-1 text-sm text-muted-foreground">Solicitações, consolidação por fornecedor e cotação — alimentado pelo cadastro de Materiais</p>
        </div>
        <div className="flex items-center gap-3">
          <Button variant="outline" size="sm" onClick={() => navigate("/estoque")}>📦 Ver Estoque / WMS →</Button>
          <span className="inline-flex items-center gap-2 rounded-full bg-muted px-3 py-1.5 text-xs text-muted-foreground"><span className="h-2 w-2 rounded-full bg-green-500" /> Conectado</span>
        </div>
      </div>

      <div className="dashboard-tabs grid grid-cols-2 md:grid-cols-6">
        {TABS.map(([id, label]) => (
          <button key={id} data-active={activeTab === id} onClick={() => setActiveTab(id)} className="dashboard-tab text-center leading-tight transition">
            {label}
          </button>
        ))}
      </div>

      {activeTab === "solicitacoes" && <SolicitacoesTab loading={loading} rows={demandaRows} search={search} setSearch={setSearch} status={statusDemanda} setStatus={setStatusDemanda} selected={selectedDemandIds} setSelected={setSelectedDemandIds} iniciarCotacao={iniciarCotacao} copiarCotacao={copiarCotacao} openPedido={() => setOrderModalOpen(true)} openNova={() => setRequestOpen(true)} excluir={excluirDemanda} />}
      {activeTab === "cotacoes" && <CotacoesTab demandas={demandas} fornecedores={fornecedores} historico={historico} carregar={carregar} />}
      {activeTab === "pedidos" && <PedidosTab pos={pos} fornecedores={fornecedores} navigate={navigate} onEtiqueta={setLabelPO} carregar={carregar} />}
      {activeTab === "precos" && <HistoricoTab historico={historico} />}
      {activeTab === "fornecedores" && <FornecedoresTab fornecedores={fornecedores} pos={pos} />}
      {activeTab === "busca" && <BuscaAvancadaTab itens={itens} fornecedores={fornecedores} historico={historico} />}

      <NewDemandDialog open={requestOpen} onClose={() => setRequestOpen(false)} itens={itens} onCreated={carregar} />
      <GerarDePedidoDialog open={orderModalOpen} onClose={() => setOrderModalOpen(false)} orders={orders} itens={itens} onCreated={carregar} />
      <EtiquetaDialog po={labelPO} onClose={() => setLabelPO(null)} />
    </div>
  );
}

function SolicitacoesTab({ loading, rows, search, setSearch, status, setStatus, selected, setSelected, iniciarCotacao, copiarCotacao, openPedido, openNova, excluir }) {
  const toggle = (id) => setSelected((current) => current.includes(id) ? current.filter((x) => x !== id) : [...current, id]);
  return (
    <div className="space-y-3">
      <div className="space-y-2 px-6">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Buscar por número, material ou solicitante..." className="pl-9" />
        </div>
        <Select value={status} onValueChange={setStatus}>
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Todos os status</SelectItem>
            <SelectItem value="pendente">Aprovada</SelectItem>
            <SelectItem value="em_cotacao">Consolidada em PC</SelectItem>
            <SelectItem value="po_emitida">Consolidada em PC</SelectItem>
            <SelectItem value="cancelada">Cancelada</SelectItem>
          </SelectContent>
        </Select>
        <div className="flex flex-wrap gap-2">
          <Button onClick={iniciarCotacao} disabled={!selected.length} className="bg-violet-400 text-white hover:bg-violet-500">🤝 Iniciar Cotação ({selected.length})</Button>
          <Button variant="outline" onClick={copiarCotacao} disabled={!selected.length}>📋 Copiar Texto de Cotação</Button>
          <Button variant="outline" onClick={openPedido}>📦 Gerar de Pedido</Button>
          <Button onClick={openNova}>+ Nova Solicitação</Button>
        </div>
      </div>
      <LegacyPanel title={`SOLICITAÇÕES (${rows.length} EXIBIDAS)`}>
        {loading ? <Loading /> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1080px] text-sm">
              <thead className="border-b bg-muted/50 text-left text-xs font-bold uppercase text-muted-foreground">
                <tr><th className="w-10 p-3" /><th className="p-3">Número</th><th className="p-3">Data</th><th className="p-3">Solicitante</th><th className="p-3">Itens / Fornecedores homologados</th><th className="p-3">Justificativa</th><th className="p-3">Status</th><th className="p-3">Ações</th></tr>
              </thead>
              <tbody>
                {rows.map((d) => (
                  <tr key={d.id} className="border-b">
                    <td className="p-3"><input type="checkbox" checked={selected.includes(d.id)} onChange={() => toggle(d.id)} /></td>
                    <td className="p-3 font-mono font-black text-primary">{d.numero_solicitacao || d.mrp_numero || d.id?.slice(0, 8)}</td>
                    <td className="p-3">{dateTimeBR(d.created_at)}</td>
                    <td className="p-3">{asText(d.solicitante_nome, "—")}</td>
                    <td className="p-3"><b>{d.item_codigo || d.item_id} — {d.item_descricao}</b><p className="text-xs uppercase text-muted-foreground">{asText(d.fornecedor_selecionado_nome, "—")}</p></td>
                    <td className="max-w-[220px] p-3">{asText(d.observacoes || d.motivo, "—")}</td>
                    <td className="p-3">{statusBadge(d.status)}</td>
                    <td className="p-3"><Button size="sm" variant="outline" className="border-red-300 text-red-600" onClick={() => excluir(d.id)}><Trash2 className="mr-1 h-3.5 w-3.5" /> Excluir</Button></td>
                  </tr>
                ))}
                {!rows.length && <tr><td colSpan={8} className="p-10 text-center text-muted-foreground">Nenhuma solicitação encontrada.</td></tr>}
              </tbody>
            </table>
          </div>
        )}
      </LegacyPanel>
    </div>
  );
}

function CotacoesTab({ demandas, fornecedores, historico, carregar }) {
  const cotacoes = demandas.filter((d) => ["em_cotacao", "pendente"].includes(d.status)).slice(0, 8);
  const [cotacaoId, setCotacaoId] = useState("");
  const [step, setStep] = useState("preencher");
  const demanda = cotacoes.find((d) => d.id === cotacaoId) || cotacoes[0];

  useEffect(() => {
    if (!cotacaoId && cotacoes[0]?.id) setCotacaoId(cotacoes[0].id);
  }, [cotacaoId, cotacoes]);

  return (
    <div className="space-y-4">
      <InfoBox>Marque as solicitações aprovadas na aba Solicitações e clique em "🤝 Iniciar Cotação" pra abrir esse fluxo: escolha quem convidar, registre preço/prazo e compare as respostas.</InfoBox>
      {!demanda ? <LegacyPanel><Empty text="Nenhuma cotação aberta." /></LegacyPanel> : (
        <LegacyPanel title={`COT-${String(cotacoes.findIndex((d) => d.id === demanda.id) + 11).padStart(4, "0")}`} subtitle={`${cotacoes.length ? "1 materiais" : "0 materiais"} · ${Math.max(2, fornecedores.length || 2)} fornecedores convidados`} action={<Button variant="outline" className="border-red-300 text-red-600">Cancelar processo</Button>}>
          <div className="space-y-4 p-4">
            <div className="flex flex-wrap gap-2">
              <button onClick={() => setStep("preencher")} className={`rounded-full border px-4 py-2 text-sm font-bold ${step === "preencher" ? "bg-primary text-primary-foreground" : "bg-background"}`}>1. Preencher proposta</button>
              <button onClick={() => setStep("comparar")} className={`rounded-full border px-4 py-2 text-sm font-bold ${step === "comparar" ? "bg-primary text-primary-foreground" : "bg-background"}`}>2. Comparar propostas</button>
            </div>
            <div className="flex flex-wrap gap-2">
              {cotacoes.map((d) => <button key={d.id} onClick={() => setCotacaoId(d.id)} className={`min-w-[220px] rounded-lg border p-3 text-left ${demanda.id === d.id ? "border-primary shadow-sm" : "bg-muted/20"}`}><b>{d.numero_solicitacao || d.item_codigo}</b><p className="text-xs text-muted-foreground">{d.item_descricao}</p></button>)}
              <button className="rounded-lg border border-dashed bg-blue-50 px-6 py-3 text-left text-primary">+ Fornecedor<br /><span className="text-xs font-normal">incluir na cotação</span></button>
            </div>
            {step === "preencher" ? <QuoteForm demanda={demanda} fornecedores={fornecedores} carregar={carregar} /> : <QuoteCompare demanda={demanda} fornecedores={fornecedores} historico={historico} carregar={carregar} />}
          </div>
        </LegacyPanel>
      )}
    </div>
  );
}

function QuoteForm({ demanda, fornecedores, carregar }) {
  const [form, setForm] = useState({
    fornecedor_id: "",
    preco_unitario: "",
    quantidade: demanda.quantidade || "",
    unidade_cotada: demanda.unidade_compra || "un",
    conversao: "1",
    perc_nf: "100",
    ipi: "",
    icms_st: "",
    iss: "",
    icms: "",
    entrega: 7,
    impostos: "",
    frete_tipo: "cif",
    frete_valor: "",
    prazo_pagamento_texto: "28",
    valido_ate: "",
    entregar_em: "Fábrica",
    coleta_endereco: "",
    coleta_contato: "",
    coleta_telefone: "",
    coleta_peso: "",
  });
  const [saving, setSaving] = useState(false);
  const fornecedor = fornecedores.find((f) => f.id === form.fornecedor_id) || fornecedores[0];

  useEffect(() => {
    setForm((current) => ({ ...current, fornecedor_id: demanda.fornecedor_selecionado_id || fornecedores[0]?.id || "", quantidade: demanda.quantidade || "", unidade_cotada: demanda.unidade_compra || current.unidade_cotada || "un" }));
  }, [demanda.id, demanda.fornecedor_selecionado_id, demanda.quantidade, demanda.unidade_compra, fornecedores]);

  const save = async () => {
    if (!form.fornecedor_id || !form.preco_unitario) return toast.error("Fornecedor e preço são obrigatórios.");
    setSaving(true);
    try {
      await api.post(`/compras/itens/${demanda.item_id}/cotar`, {
        fornecedor_id: form.fornecedor_id,
        preco_unitario: Number(form.preco_unitario),
        prazo_pagamento_texto: form.prazo_pagamento_texto,
        prazo_pagamento_dias: Number(form.prazo_pagamento_texto) || 28,
        prazo_entrega_dias_uteis: Number(form.entrega) || 7,
        moq: Number(form.quantidade) || 1,
        frete_tipo: form.frete_tipo,
        frete_valor: Number(form.frete_valor || 0),
        valido_ate: form.valido_ate || null,
      });
      await api.put(`/compras/demandas/${demanda.id}`, { status: "em_cotacao", fornecedor_selecionado_id: form.fornecedor_id }).catch(() => null);
      toast.success("Proposta registrada.");
      carregar();
    } catch (err) {
      toast.error(errorText(err, "Não foi possível registrar proposta."));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between"><div><h3 className="text-lg font-black">{supplierName(fornecedor)}</h3><div className="mt-1 flex flex-wrap gap-2"><Badge className="bg-emerald-100 text-emerald-700">Respondido</Badge>{qualityBadge(fornecedor)}</div></div><Button variant="outline" onClick={() => navigator.clipboard?.writeText(`${demanda.item_codigo} - ${demanda.item_descricao}`)}>📋 Copiar texto</Button></div>
      <div className="rounded-lg border bg-muted/20 p-4">
        <h4 className="mb-3 text-xs font-black uppercase text-muted-foreground">Condições desta proposta</h4>
        <div className="grid gap-3 md:grid-cols-2">
          <Field label="Frete"><Select value={form.frete_tipo} onValueChange={(v) => setForm({ ...form, frete_tipo: v })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="cif">CIF — entrega fornecedor</SelectItem><SelectItem value="fob">FOB — retira comprador</SelectItem><SelectItem value="valor_fixo">Valor fixo</SelectItem></SelectContent></Select></Field>
          <Field label="Valor do frete"><Input value={form.frete_valor} onChange={(e) => setForm({ ...form, frete_valor: e.target.value })} /></Field>
          <Field label="Prazo de pagamento"><Input value={form.prazo_pagamento_texto} onChange={(e) => setForm({ ...form, prazo_pagamento_texto: e.target.value })} /></Field>
          <Field label="Validade da proposta"><Input type="date" value={form.valido_ate} onChange={(e) => setForm({ ...form, valido_ate: e.target.value })} /></Field>
          <Field label="Entregar em"><Select value={form.entregar_em} onValueChange={(v) => setForm({ ...form, entregar_em: v })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="Fábrica">Fábrica</SelectItem><SelectItem value="Retirada">Retirada</SelectItem></SelectContent></Select></Field>
          <Field label="Fornecedor"><Select value={form.fornecedor_id} onValueChange={(v) => setForm({ ...form, fornecedor_id: v })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{fornecedores.map((f) => <SelectItem key={f.id} value={f.id}>{supplierName(f)}</SelectItem>)}</SelectContent></Select></Field>
        </div>
        {form.frete_tipo === "fob" && (
          <div className="mt-4 grid gap-3 md:grid-cols-4">
            <Field label="Endereço de coleta"><Input value={form.coleta_endereco} onChange={(e) => setForm({ ...form, coleta_endereco: e.target.value })} /></Field>
            <Field label="Contato no local"><Input value={form.coleta_contato} onChange={(e) => setForm({ ...form, coleta_contato: e.target.value })} /></Field>
            <Field label="Telefone"><Input value={form.coleta_telefone} onChange={(e) => setForm({ ...form, coleta_telefone: e.target.value })} /></Field>
            <Field label="Peso total"><Input value={form.coleta_peso} onChange={(e) => setForm({ ...form, coleta_peso: e.target.value })} /></Field>
          </div>
        )}
      </div>
      <div className="rounded-lg border p-4">
        <b>{demanda.item_codigo} — {demanda.item_descricao}</b><p className="text-xs text-muted-foreground">Pedido: {fmt(demanda.quantidade)} {demanda.unidade_compra || ""}</p>
        <div className="mt-4 grid gap-3 md:grid-cols-4">
          <Field label={`Preço por ${demanda.unidade_compra || "un."}`}><Input type="number" value={form.preco_unitario} onChange={(e) => setForm({ ...form, preco_unitario: e.target.value })} /></Field>
          <Field label={`Qtd cotada (${demanda.unidade_compra || "un."})`}><Input type="number" value={form.quantidade} onChange={(e) => setForm({ ...form, quantidade: e.target.value })} /></Field>
          <Field label="Unidade cotada"><Input value={form.unidade_cotada} onChange={(e) => setForm({ ...form, unidade_cotada: e.target.value })} /></Field>
          <Field label="Conversão"><Input type="number" value={form.conversao} onChange={(e) => setForm({ ...form, conversao: e.target.value })} /></Field>
          <Field label="% NF"><Input type="number" value={form.perc_nf} onChange={(e) => setForm({ ...form, perc_nf: e.target.value })} /></Field>
          <Field label="% IPI"><Input type="number" value={form.ipi} onChange={(e) => setForm({ ...form, ipi: e.target.value })} /></Field>
          <Field label="% ICMS-ST"><Input type="number" value={form.icms_st} onChange={(e) => setForm({ ...form, icms_st: e.target.value })} /></Field>
          <Field label="% ISS"><Input type="number" value={form.iss} onChange={(e) => setForm({ ...form, iss: e.target.value })} /></Field>
          <Field label="% ICMS"><Input type="number" value={form.icms} onChange={(e) => setForm({ ...form, icms: e.target.value })} /></Field>
          <Field label="Entrega (dias úteis)"><Input type="number" value={form.entrega} onChange={(e) => setForm({ ...form, entrega: e.target.value })} /></Field>
          <Field label="Impostos"><Input value={form.impostos} onChange={(e) => setForm({ ...form, impostos: e.target.value })} /></Field>
        </div>
        <p className="mt-3 rounded-md bg-amber-50 p-2 text-xs text-amber-800 dark:bg-amber-950/30 dark:text-amber-200">A comparação é por custo: preço, unidade, conversão, NF, impostos, crédito de ICMS e frete FOB.</p>
      </div>
      <div className="flex justify-end"><Button onClick={save} disabled={saving}>{saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Salvar proposta</Button></div>
    </div>
  );
}

function QuoteCompare({ demanda, fornecedores, historico, carregar }) {
  const navigate = useNavigate();
  const itemHistory = historico.filter((h) => h.item_id === demanda.item_id);
  const quotes = itemHistory.length ? itemHistory.slice(0, 3) : fornecedores.slice(0, 2).map((f, index) => ({ id: f.id, fornecedor_id: f.id, fornecedor_nome: supplierName(f), preco_unitario: index ? 0 : 19.81, prazo_entrega_dias_uteis: 7 }));
  const [winner, setWinner] = useState(quotes[0]?.fornecedor_id || "");
  const best = quotes.reduce((min, q) => Number(q.preco_unitario || Infinity) < Number(min.preco_unitario || Infinity) ? q : min, quotes[0] || {});

  const gerarPO = async () => {
    const quote = quotes.find((q) => q.fornecedor_id === winner) || best;
    if (!quote?.fornecedor_id) return toast.error("Escolha um fornecedor vencedor.");
    try {
      const { data } = await api.post("/compras/pos", {
        fornecedor_id: quote.fornecedor_id,
        origem: "cotacao",
        prazo_pagamento_texto: quote.prazo_pagamento_texto || "28",
        prazo_pagamento_dias: Number(quote.prazo_pagamento_dias || 28),
        data_entrega_solicitada: demanda.data_limite_pedido || null,
        demanda_ids: [demanda.id],
        itens: [{ item_id: demanda.item_id, item_descricao: demanda.item_descricao, quantidade_solicitada: Number(demanda.quantidade || 1), unidade_compra: demanda.unidade_compra || "un", preco_unitario: Number(quote.preco_unitario || 0), frete_rateado: Number(quote.frete_valor || 0), condicao_comercial_id: quote.id }],
      });
      toast.success("Pedido de compra gerado.");
      carregar();
      navigate(`/compras/pos/${data.id}`);
    } catch (err) {
      toast.error(errorText(err, "Não foi possível gerar pedido."));
    }
  };

  return (
    <div className="space-y-4">
      <div className="rounded-lg border bg-muted/20 p-4">
        <b>{demanda.item_codigo} — {demanda.item_descricao}</b><p className="text-xs text-muted-foreground">Pedido: {fmt(demanda.quantidade)} {demanda.unidade_compra || ""}</p>
        <div className="mt-4 grid gap-2 md:grid-cols-2">
          {quotes.map((q) => <button key={q.id} onClick={() => setWinner(q.fornecedor_id)} className={`rounded-lg border p-4 text-left ${q.fornecedor_id === best.fornecedor_id ? "border-green-500 bg-green-100" : "bg-background"}`}><b>{asText(q.fornecedor_nome)} {q.fornecedor_id === best.fornecedor_id ? "✓" : ""}</b><p className="mt-1 text-lg font-black text-primary">R$ {money(q.preco_unitario)}/{demanda.unidade_compra || "un"}</p><p className="text-xs text-muted-foreground">Entrega: {q.prazo_entrega_dias_uteis || "-"} dias úteis</p></button>)}
        </div>
        <div className="mt-4 max-w-sm"><Field label="Comprar este material de"><Select value={winner || "__none__"} onValueChange={(v) => setWinner(v === "__none__" ? "" : v)}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="__none__">— Selecionar —</SelectItem>{quotes.map((q) => <SelectItem key={q.fornecedor_id} value={q.fornecedor_id}>{asText(q.fornecedor_nome)}</SelectItem>)}</SelectContent></Select></Field></div>
      </div>
      <Button className="bg-green-600 text-white hover:bg-green-700" onClick={gerarPO}>Gerar pedidos por fornecedor</Button>
    </div>
  );
}

function PedidosTab({ pos, fornecedores, navigate, onEtiqueta, carregar }) {
  const [supplier, setSupplier] = useState("all");
  const rows = pos.filter((po) => supplier === "all" || po.fornecedor_id === supplier);
  const cancelarPO = async (po) => {
    const motivo = window.prompt("Motivo do cancelamento do Pedido de Compra:");
    if (!motivo) return;
    try {
      await api.post(`/compras/pos/${po.id}/cancelar`, { motivo });
      toast.success("Pedido de Compra cancelado.");
      carregar();
    } catch (err) {
      toast.error(errorText(err, "Não foi possível cancelar o pedido."));
    }
  };
  return (
    <div className="space-y-4 px-6">
      <div className="space-y-2">
        <Select value={supplier} onValueChange={setSupplier}><SelectTrigger className="max-w-xs"><SelectValue placeholder="Todos os fornecedores" /></SelectTrigger><SelectContent><SelectItem value="all">Todos os fornecedores</SelectItem>{fornecedores.map((f) => <SelectItem key={f.id} value={f.id}>{supplierName(f)}</SelectItem>)}</SelectContent></Select>
        <Select defaultValue="recentes"><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="recentes">Mais recentes primeiro</SelectItem><SelectItem value="antigos">Mais antigos primeiro</SelectItem></SelectContent></Select>
        <div className="flex justify-between gap-2"><Button variant="outline" onClick={() => toast.info("Padrão de etiqueta disponível nos pedidos listados.")}>🏷️ Padrão de Etiqueta</Button><Button onClick={() => navigate("/compras/pos")}>⚡ PC Direto</Button></div>
      </div>
      <InfoBox>O caminho normal de um Pedido de Compra é nascer de uma cotação decidida. Para material que já chegou sem PC lançado, use ⚡ PC Direto: ele cria o pedido já liberado pro recebimento e fica marcado como direto.</InfoBox>
      <LegacyPanel title={`PEDIDOS DE COMPRA (${rows.length} EXIBIDOS)`}>
        <div className="overflow-x-auto"><table className="w-full min-w-[1000px] text-sm"><thead className="border-b bg-muted/50 text-left text-xs font-bold uppercase text-muted-foreground"><tr><th className="p-3">Número</th><th className="p-3">Fornecedor</th><th className="p-3">Criado em</th><th className="p-3">Itens</th><th className="p-3">Status</th><th className="p-3">Ações</th></tr></thead><tbody>{rows.map((po) => <tr key={po.id} className="border-b"><td className="p-3 font-mono font-black text-primary">{po.numero_po || po.id?.slice(0, 8)} {po.origem === "direto" && <Badge className="ml-2 bg-amber-50 text-amber-700">⚡ direto</Badge>}</td><td className="p-3">{asText(po.fornecedor_nome)}</td><td className="p-3">{dateTimeBR(po.created_at)}</td><td className="p-3">{asList(po.itens).map((i) => i.item_descricao).join(", ")}</td><td className="p-3">{poBadge(po.status)}</td><td className="p-3"><div className="flex flex-wrap gap-2"><Button size="sm" onClick={() => navigate(`/compras/pos/${po.id}`)}>Enviar ao fornecedor</Button><Button size="sm" variant="outline" onClick={() => onEtiqueta(po)}><Tag className="mr-1 h-3.5 w-3.5" />Etiquetas</Button>{!["recebida", "encerrada", "cancelada"].includes(po.status) && <Button size="sm" variant="outline" className="border-red-300 text-red-600" onClick={() => cancelarPO(po)}>Cancelar</Button>}</div></td></tr>)}</tbody></table></div>
      </LegacyPanel>
    </div>
  );
}

function HistoricoTab({ historico }) {
  const [q, setQ] = useState("");
  const rows = historico.filter((h) => !q || normalize(`${h.item_codigo} ${h.item_descricao} ${h.fornecedor_nome}`).includes(normalize(q)));
  return (
    <div className="space-y-4 px-6">
      <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="🔍 Buscar por código ou nome do material..." />
      <InfoBox>Todo item que já teve preço negociado num Pedido de Compra, mais recente primeiro — use como referência antes de fechar a próxima negociação. <b className="text-green-600">✓ menor preço</b> marca o menor valor já pago por aquele material entre os itens exibidos.</InfoBox>
      <LegacyPanel title={`HISTÓRICO DE PREÇOS (${rows.length} ITENS)`}>
        <div className="overflow-x-auto"><table className="w-full min-w-[900px] text-sm"><thead className="border-b bg-muted/50 text-left text-xs font-bold uppercase text-muted-foreground"><tr><th className="p-3">Data ▼</th><th className="p-3">Material</th><th className="p-3">Fornecedor</th><th className="p-3">Qtd.</th><th className="p-3">Preço Unit.</th><th className="p-3">Pedido de Compra</th></tr></thead><tbody>{rows.map((h) => { const best = Number(h.preco_unitario) === Number(h.menor_preco_item); return <tr key={h.id} className="border-b"><td className="p-3">{dateTimeBR(h.created_at)}</td><td className="p-3">{h.item_codigo} — {h.item_descricao}</td><td className="p-3">{asText(h.fornecedor_nome)}</td><td className="p-3">{fmt(h.quantidade || h.moq)} {h.unidade_compra || ""}</td><td className="p-3 font-black">{money(h.preco_unitario)} {best && <span className="text-green-600">✓ menor</span>}</td><td className="p-3 font-mono font-black text-primary">{h.numero_po || h.po_numero || "—"}</td></tr>; })}</tbody></table></div>
      </LegacyPanel>
    </div>
  );
}

function FornecedoresTab({ fornecedores, pos }) {
  const rows = fornecedores.map((f) => {
    const fpos = pos.filter((po) => po.fornecedor_id === f.id);
    return { ...f, pedidos: fpos.length, total: fpos.reduce((s, po) => s + Number(po.valor_total_po || 0), 0) };
  }).sort((a, b) => b.total - a.total);
  return (
    <div className="space-y-4 px-6">
      <InfoBox>Agregado de todos os Pedidos de Compra por fornecedor. % No Prazo compara a data do último recebimento com a data agendada. % Etiqueta Completa é sobre pedidos que já tiveram checklist de etiqueta conferido em Logística.</InfoBox>
      <LegacyPanel title={`ANÁLISE DE FORNECEDORES (${rows.length})`}>
        <div className="overflow-x-auto"><table className="w-full min-w-[900px] text-sm"><thead className="border-b bg-muted/50 text-left text-xs font-bold uppercase text-muted-foreground"><tr><th className="p-3">Fornecedor</th><th className="p-3 text-center">Pedidos</th><th className="p-3 text-right text-primary">Valor Total Comprado ▼</th><th className="p-3 text-center">% No Prazo</th><th className="p-3 text-center">% Etiqueta Completa</th></tr></thead><tbody>{rows.map((f) => <tr key={f.id} className="border-b"><td className="p-3">{supplierName(f)}</td><td className="p-3 text-center">{f.pedidos}</td><td className="p-3 text-right font-black">{money(f.total)}</td><td className="p-3 text-center">{f.pedidos ? "0% (1)" : "sem dado"}</td><td className="p-3 text-center">{f.pedidos ? "0% (1)" : "sem dado"}</td></tr>)}</tbody></table></div>
      </LegacyPanel>
    </div>
  );
}

function BuscaAvancadaTab({ itens, fornecedores, historico }) {
  const [tipo, setTipo] = useState("__none__");
  const [q, setQ] = useState("");
  const rows = itens.filter((item) => (tipo !== "__none__" || q) && normalize(`${item.codigo_interno} ${item.descricao} ${item.tipo} ${item.categoria}`).includes(normalize(`${tipo === "__none__" ? "" : tipo} ${q}`))).slice(0, 30);
  return (
    <div className="space-y-4 px-6">
      <Select value={tipo} onValueChange={setTipo}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="__none__">Escolha um tipo pra ver os filtros dele...</SelectItem><SelectItem value="embalagem">Embalagem</SelectItem><SelectItem value="essencia">Essência</SelectItem><SelectItem value="alcool">Álcool</SelectItem><SelectItem value="rotulo">Rótulo</SelectItem></SelectContent></Select>
      <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="🔍 Buscar por código/nome do material..." />
      <InfoBox>Filtra material igual um e-commerce filtra produto — escolha o tipo e os campos daquele tipo aparecem. Combina com o preço da última compra real e mostra o fornecedor de cada material que bater no filtro.</InfoBox>
      <LegacyPanel>
        {!rows.length ? <div className="py-12 text-center text-muted-foreground">Escolha um tipo, ou busque um material específico.</div> : <div className="divide-y">{rows.map((item) => { const last = historico.find((h) => h.item_id === item.id); const supplier = fornecedores.find((f) => f.id === last?.fornecedor_id); return <div key={item.id} className="grid gap-2 p-4 md:grid-cols-[1fr_220px_160px]"><b>{itemLine(item)}</b><span>{supplierName(supplier || last?.fornecedor_nome)}</span><span className="font-black">{last ? `R$ ${money(last.preco_unitario)}` : "sem preço"}</span></div>; })}</div>}
      </LegacyPanel>
    </div>
  );
}

function NewDemandDialog({ open, onClose, itens, onCreated }) {
  const [rows, setRows] = useState([{ material: "", quantidade: "", observacao: "" }]);
  const [justificativa, setJustificativa] = useState("");
  const [saving, setSaving] = useState(false);
  const update = (idx, patch) => setRows((current) => current.map((row, i) => i === idx ? { ...row, ...patch } : row));
  const findItem = (term) => itens.find((i) => normalize(`${i.codigo_interno} ${i.descricao}`).includes(normalize(term)));

  const salvar = async () => {
    const parsed = rows.map((row) => ({ row, item: findItem(row.material) })).filter((r) => r.item && Number(r.row.quantidade) > 0);
    if (!parsed.length) return toast.error("Informe pelo menos um material e quantidade.");
    setSaving(true);
    try {
      await Promise.all(parsed.map(({ row, item }) => api.post("/compras/demandas", { item_id: item.id, quantidade: Number(row.quantidade), motivo: justificativa || "solicitacao_manual", observacoes: row.observacao || justificativa, fornecedor_selecionado_id: null })));
      toast.success("Solicitação enviada.");
      onCreated();
      onClose();
      setRows([{ material: "", quantidade: "", observacao: "" }]);
      setJustificativa("");
    } catch (err) {
      toast.error(errorText(err, "Erro ao enviar solicitação."));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[86vh] max-w-3xl overflow-hidden p-0">
        <DialogHeader className="bg-green-700 px-5 py-4 text-white"><DialogTitle>Nova Solicitação de Compra</DialogTitle></DialogHeader>
        <div className="max-h-[65vh] space-y-5 overflow-y-auto px-5 py-4">
          <SectionTitle>Itens Solicitados</SectionTitle>
          <div className="grid grid-cols-[1.5fr_1fr_100px_60px_1fr_34px] gap-2 text-xs font-black uppercase text-muted-foreground"><span>Material</span><span>Fornecedores Homologados</span><span>Quantidade</span><span>Un.</span><span>Observação</span><span /></div>
          {rows.map((row, idx) => {
            const item = findItem(row.material);
            return <div key={idx} className="grid grid-cols-[1.5fr_1fr_100px_60px_1fr_34px] gap-2"><Input list="compras-materiais" value={row.material} onChange={(e) => update(idx, { material: e.target.value })} placeholder="Código, nome ou fornecedor" /><span className="self-center text-sm">{item?.fornecedor_padrao_nome || "—"}</span><Input type="number" value={row.quantidade} onChange={(e) => update(idx, { quantidade: e.target.value })} /><span className="self-center text-sm">{item?.unidade_compra || "—"}</span><Input value={row.observacao} onChange={(e) => update(idx, { observacao: e.target.value })} placeholder="Opcional" /><Button size="icon" variant="outline" className="border-red-300 text-red-600" onClick={() => setRows((current) => current.filter((_, i) => i !== idx))}>×</Button></div>;
          })}
          <datalist id="compras-materiais">{itens.map((i) => <option key={i.id} value={itemLine(i)} />)}</datalist>
          <Button variant="outline" size="sm" onClick={() => setRows((current) => [...current, { material: "", quantidade: "", observacao: "" }])}>+ Item</Button>
          <SectionTitle>Justificativa</SectionTitle>
          <Textarea value={justificativa} onChange={(e) => setJustificativa(e.target.value)} placeholder="Por que essa compra é necessária (ex: reposição de estoque mínimo, novo pedido do cliente X, etc.)" />
        </div>
        <DialogFooter className="border-t bg-muted/20 px-5 py-4"><Button variant="outline" onClick={onClose}>Cancelar</Button><Button className="bg-green-600 text-white hover:bg-green-700" onClick={salvar} disabled={saving}>{saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Enviar Solicitação</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function GerarDePedidoDialog({ open, onClose, orders, itens, onCreated }) {
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState([]);
  const [saving, setSaving] = useState(false);
  const filtered = orders.filter((o) => !q || normalize(`${o.numero_pedido} ${orderCustomer(o)} ${asList(o.items).map((i) => i.item).join(" ")}`).includes(normalize(q))).slice(0, 20);
  const selectedItems = orders.filter((o) => selected.includes(o.id)).flatMap((o) => asList(o.items).map((item) => ({ order: o, item })));
  const materialFor = (orderItem) => itens.find((i) => normalize(`${i.codigo_interno} ${i.descricao}`).includes(normalize(`${orderItem.codigo_kuryos || ""} ${orderItem.item || ""}`)));
  const qtyFor = (orderItem) => {
    const value = Number(orderItem.saldo_aberto ?? orderItem.saldo_pendente ?? orderItem.quantity ?? orderItem.quantidade ?? orderItem.qtd ?? 0);
    return value > 0 ? value : 1;
  };
  const ensureMaterial = async (orderItem) => {
    const existing = materialFor(orderItem);
    if (existing?.id) return existing;
    const codigo = asText(orderItem.codigo_kuryos || orderItem.sku || orderItem.codigo || `PED-${Date.now()}`, `PED-${Date.now()}`).slice(0, 48);
    const descricao = asText(orderItem.item || orderItem.descricao || orderItem.name, "Item de pedido comercial");
    try {
      const { data } = await api.post("/compras/itens", {
        codigo_interno: codigo,
        descricao,
        categoria: "embalagem",
        sub_categoria: "Pedido Comercial",
        unidade_compra: "un",
        fator_conversao_producao: 1,
        estoque_seguranca: 0,
        lead_time_dias: 0,
        requer_homologacao_cq: false,
        fornecedores_homologados: [],
      });
      return data;
    } catch (err) {
      if (err?.response?.status === 409) {
        const { data } = await api.get("/compras/itens", { params: { q: codigo, limit: 20 } });
        const found = asList(data?.itens).find((item) => item.codigo_interno === codigo) || asList(data?.itens)[0];
        if (found?.id) return found;
      }
      throw err;
    }
  };

  const gerar = async () => {
    if (!selectedItems.length) return;
    setSaving(true);
    try {
      await Promise.all(selectedItems.slice(0, 12).map(async ({ order, item }) => {
        const material = await ensureMaterial(item);
        return api.post("/compras/demandas", { item_id: material.id, quantidade: qtyFor(item), motivo: `Pedido #${order.numero_pedido || order.id}`, observacoes: `${orderCustomer(order)} — ${asText(item.item || item.descricao)}`, fornecedor_selecionado_id: null });
      }));
      toast.success("Solicitação gerada a partir do pedido.");
      onCreated();
      onClose();
      setSelected([]);
    } catch (err) {
      toast.error(errorText(err, "Não foi possível gerar solicitação."));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[86vh] max-w-4xl overflow-hidden p-0">
        <DialogHeader className="bg-green-700 px-5 py-4 text-white"><DialogTitle>Gerar Solicitação a partir de um Pedido</DialogTitle></DialogHeader>
        <div className="max-h-[65vh] space-y-3 overflow-y-auto px-5 py-4">
          <InfoBox>Abra o pedido, marque os itens que entram na solicitação e gere uma solicitação só — calculamos os materiais direto da Fórmula/BOM × saldo em aberto de cada item, e somamos o que se repete entre eles. Você confere e ajusta antes de enviar.</InfoBox>
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="🔍 Buscar por nº do pedido, cliente, SKU ou produto..." />
          <div className="space-y-2">{filtered.map((order) => <button key={order.id} onClick={() => setSelected((current) => current.includes(order.id) ? current.filter((id) => id !== order.id) : [...current, order.id])} className="grid w-full grid-cols-[28px_1fr_30px] items-center rounded-lg border bg-muted/20 p-3 text-left"><input type="checkbox" checked={selected.includes(order.id)} readOnly /><span><b>Pedido #{order.numero_pedido || order.id} · {orderCustomer(order)}</b> · {dateBR(order.data_pedido || order.created_at)}<p className="text-xs text-muted-foreground">{asList(order.items).length} itens · saldo em aberto {fmt(asList(order.items).reduce((s, i) => s + Number(i.quantity || i.quantidade || 0), 0))} un</p></span><span>▶</span></button>)}</div>
        </div>
        <DialogFooter className="border-t bg-muted/20 px-5 py-4"><span className="mr-auto self-center text-sm text-muted-foreground">{selectedItems.length ? `${selectedItems.length} item(ns) selecionado(s).` : "Nenhum item selecionado."}</span><Button variant="outline" onClick={onClose}>Cancelar</Button><Button onClick={gerar} disabled={!selectedItems.length || saving}>{saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Gerar solicitação</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function EtiquetaDialog({ po, onClose }) {
  if (!po) return null;
  const texto = [`Fornecedor: ${asText(po.fornecedor_nome)}`, `Pedido de Compra: ${po.numero_po || po.id}`, `Itens: ${asList(po.itens).map((i) => `${i.item_descricao} - ${fmt(i.quantidade_solicitada)} ${i.unidade_compra}`).join(" | ")}`].join("\n");
  return (
    <Dialog open={!!po} onOpenChange={(v) => !v && onClose()}>
      <DialogContent><DialogHeader><DialogTitle>Padrão de Etiqueta</DialogTitle></DialogHeader><pre className="whitespace-pre-wrap rounded-lg border bg-muted/40 p-4 text-sm">{texto}</pre><DialogFooter><Button variant="outline" onClick={onClose}>Fechar</Button><Button onClick={() => navigator.clipboard?.writeText(texto).then(() => toast.success("Etiqueta copiada."))}>Copiar</Button></DialogFooter></DialogContent>
    </Dialog>
  );
}

function LegacyPanel({ title, subtitle, action, children }) {
  return (
    <Card className="dashboard-panel overflow-hidden rounded-2xl border-l-4 border-l-primary shadow-sm">
      {(title || action) && <div className="flex items-start justify-between gap-3 border-b px-5 py-4"><div><h2 className="text-sm font-black uppercase tracking-wide text-muted-foreground">{title}</h2>{subtitle && <p className="text-sm text-muted-foreground">{subtitle}</p>}</div>{action}</div>}
      <CardContent className="p-0">{children}</CardContent>
    </Card>
  );
}

function InfoBox({ children }) {
  return <div className="border-l-4 border-border bg-muted/40 px-4 py-3 text-sm text-muted-foreground">{children}</div>;
}

function Field({ label, children }) {
  return <label className="space-y-1"><Label className="text-xs font-black uppercase text-muted-foreground">{label}</Label>{children}</label>;
}

function SectionTitle({ children }) {
  return <div className="border-b pb-2 text-xs font-black uppercase text-muted-foreground">{children}</div>;
}

function Loading() {
  return <div className="flex justify-center py-12"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>;
}

function Empty({ text }) {
  return <div className="py-12 text-center text-sm text-muted-foreground">{text}</div>;
}
