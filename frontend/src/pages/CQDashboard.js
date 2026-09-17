import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  Check,
  ChevronRight,
  ClipboardList,
  FlaskConical,
  Loader2,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
} from "lucide-react";
import { toast } from "sonner";

import api from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/contexts/AuthContext";

const emptyRnc = {
  classificacao: "maior",
  origem: "recepcao_mp",
  item_nome: "",
  fornecedor_id: "",
  fornecedor_nome: "",
  lote_numero: "",
  quantidade_afetada: "",
  unidade: "un",
  disposicao_imediata: "devolucao",
  descricao: "",
  prazo_resolucao: "",
};

const emptyClose = {
  causa_raiz: "",
  acao_corretiva: "",
  disposicao_material: "devolucao",
  evidencia_resolucao: "",
  com_concessao: false,
  autorizacao_concessao: "",
};

function apiError(error, fallback) {
  const detail = error?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (detail?.message) return detail.message;
  return fallback;
}

function Field({ label, children }) {
  return (
    <label className="block space-y-1">
      <Label className="text-xs font-black uppercase text-muted-foreground">{label}</Label>
      {children}
    </label>
  );
}

function fmtDate(value) {
  if (!value) return "-";
  try {
    return new Date(value).toLocaleDateString("pt-BR");
  } catch {
    return String(value);
  }
}

function daysOpen(row) {
  const base = row.created_at || row.data_criacao || row.nf_data;
  if (!base) return 0;
  const diff = Date.now() - new Date(base).getTime();
  return Math.max(0, Math.floor(diff / 86400000));
}

function StatusBadge({ value }) {
  const v = value || "pendente";
  const cls = {
    rascunho: "bg-slate-100 text-slate-700",
    em_analise: "bg-blue-100 text-blue-700",
    aprovado: "bg-emerald-100 text-emerald-700",
    concessao: "bg-purple-100 text-purple-700",
    reprovado: "bg-red-100 text-red-700",
    retido: "bg-amber-100 text-amber-700",
    aberta: "bg-red-100 text-red-700",
    em_investigacao: "bg-blue-100 text-blue-700",
    encerrada: "bg-emerald-100 text-emerald-700",
    encerrada_concessao: "bg-purple-100 text-purple-700",
    critica: "bg-red-100 text-red-700",
    maior: "bg-amber-100 text-amber-700",
    menor: "bg-emerald-100 text-emerald-700",
  }[v] || "bg-slate-100 text-slate-700";
  return <Badge className={`${cls} border-0`}>{String(v).replaceAll("_", " ")}</Badge>;
}

function Stat({ icon: Icon, label, value, tone = "text-primary" }) {
  return (
    <div className="dashboard-kpi rounded-lg border bg-card p-4 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase text-muted-foreground">{label}</p>
          <p className={`mt-1 text-2xl font-black ${tone}`}>{value}</p>
        </div>
        <Icon className={`h-5 w-5 ${tone}`} />
      </div>
    </div>
  );
}

export default function CQDashboard() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [tab, setTab] = useState("fila");
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [ras, setRas] = useState([]);
  const [rncs, setRncs] = useState([]);
  const [fornecedores, setFornecedores] = useState([]);
  const [produtos, setProdutos] = useState([]);
  const [rncOpen, setRncOpen] = useState(false);
  const [closeOpen, setCloseOpen] = useState(false);
  const [selectedRnc, setSelectedRnc] = useState(null);
  const [rncForm, setRncForm] = useState(emptyRnc);
  const [closeForm, setCloseForm] = useState(emptyClose);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [raRes, rncRes, fornRes, prodRes] = await Promise.all([
        api.get("/cq/registros-analise", { params: { limit: 200 } }),
        api.get("/cq/rncs", { params: { limit: 200 } }),
        api.get("/cadastros/fornecedores").catch(() => ({ data: { fornecedores: [] } })),
        api.get("/cadastros/produtos").catch(() => ({ data: { produtos: [] } })),
      ]);
      setRas(Array.isArray(raRes.data) ? raRes.data : (raRes.data?.items || raRes.data?.data || []));
      setRncs(Array.isArray(rncRes.data) ? rncRes.data : (rncRes.data?.items || rncRes.data?.data || []));
      setFornecedores(fornRes.data?.fornecedores || []);
      setProdutos(prodRes.data?.produtos || []);
    } catch (error) {
      toast.error(apiError(error, "Erro ao carregar Qualidade."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const filteredRas = ras.filter((ra) => `${ra.numero_ra} ${ra.item_nome} ${ra.lote_numero} ${ra.fornecedor_nome} ${ra.nf_numero}`.toLowerCase().includes(q.toLowerCase()));
  const openRncs = rncs
    .filter((rnc) => !["encerrada", "encerrada_concessao"].includes(rnc.status))
    .filter((rnc) => `${rnc.numero_rnc} ${rnc.item_nome} ${rnc.fornecedor_nome} ${rnc.descricao}`.toLowerCase().includes(q.toLowerCase()))
    .sort((a, b) => {
      const statusScore = (v) => v === "aberta" ? 0 : 1;
      const classScore = (v) => v === "critica" ? 0 : v === "maior" ? 1 : 2;
      return statusScore(a.status) - statusScore(b.status) || classScore(a.classificacao) - classScore(b.classificacao) || daysOpen(b) - daysOpen(a);
    });

  const specs = produtos.flatMap((produto) => {
    const spec = produto.especificacoes_tecnicas || {};
    return Object.entries(spec).filter(([, value]) => value).map(([name, value]) => ({
      id: `${produto.id}-${name}`,
      produto,
      name,
      value,
      numeric: /min|max|ph|densidade|viscosidade|peso|volume/i.test(name) || /\d/.test(String(value)),
      critical: /crit|micro|ph|densidade|viscosidade/i.test(name),
    }));
  });

  const supplierRows = fornecedores.map((forn) => {
    const supplierRncs = rncs.filter((rnc) => rnc.fornecedor_id === forn.id || rnc.fornecedor_nome === forn.razao_social);
    const abertas = supplierRncs.filter((rnc) => !["encerrada", "encerrada_concessao"].includes(rnc.status)).length;
    const rejeicoes = supplierRncs.length;
    const aprovadas = ras.filter((ra) => (ra.fornecedor_id === forn.id || ra.fornecedor_nome === forn.razao_social) && ra.status === "aprovado").length;
    const concessoes = ras.filter((ra) => (ra.fornecedor_id === forn.id || ra.fornecedor_nome === forn.razao_social) && ra.status === "concessao").length;
    const total = aprovadas + concessoes + rejeicoes;
    const taxa = total ? Math.round((aprovadas / total) * 100) : null;
    return { ...forn, taxa, rncs: rejeicoes, abertas };
  }).sort((a, b) => (a.taxa ?? -1) - (b.taxa ?? -1));

  async function decideRa(ra, decisao) {
    const payload = { decisao, observacoes: "" };
    if (decisao === "concessao") {
      const autorizacao = window.prompt("Quem autorizou a concessao?");
      if (!autorizacao) return;
      payload.justificativa_concessao = autorizacao;
    }
    if (decisao === "reprovado") {
      const motivo = window.prompt("Motivo da reprova / descricao da nao conformidade:");
      if (!motivo) return;
      payload.disposicao_imediata = "devolucao";
      payload.observacoes = motivo;
    }
    if (decisao === "retido") {
      const motivo = window.prompt("Motivo da retencao:");
      if (!motivo) return;
      payload.decisao = "reprovado";
      payload.disposicao_imediata = "concessao";
      payload.observacoes = `Retido: ${motivo}`;
    }
    setSaving(true);
    try {
      await api.post(`/cq/registros-analise/${ra.id}/aprovar`, payload);
      toast.success("Decisao registrada.");
      load();
    } catch (error) {
      toast.error(apiError(error, "Nao foi possivel registrar decisao."));
    } finally {
      setSaving(false);
    }
  }

  async function createRnc() {
    if (!rncForm.descricao.trim()) return toast.error("Descreva a nao conformidade.");
    setSaving(true);
    try {
      await api.post("/cq/rncs", {
        ...rncForm,
        quantidade_afetada: rncForm.quantidade_afetada ? Number(rncForm.quantidade_afetada) : null,
        fornecedor_nome: rncForm.fornecedor_nome || fornecedores.find((f) => f.id === rncForm.fornecedor_id)?.razao_social || "",
      });
      toast.success("RNC aberta.");
      setRncOpen(false);
      setRncForm(emptyRnc);
      load();
    } catch (error) {
      toast.error(apiError(error, "Nao foi possivel abrir RNC."));
    } finally {
      setSaving(false);
    }
  }

  async function assumeRnc(rnc) {
    setSaving(true);
    try {
      await api.put(`/cq/rncs/${rnc.id}`, {
        responsavel_id: user?.id || "atual",
        responsavel_nome: user?.name || user?.email || "Analista CQ",
        prazo_resolucao: rnc.prazo_resolucao || new Date(Date.now() + 7 * 86400000).toISOString().slice(0, 10),
      });
      toast.success("RNC assumida.");
      load();
    } catch (error) {
      toast.error(apiError(error, "Nao foi possivel assumir RNC."));
    } finally {
      setSaving(false);
    }
  }

  async function closeRnc() {
    if (!closeForm.causa_raiz.trim() || !closeForm.acao_corretiva.trim() || !closeForm.disposicao_material) {
      return toast.error("Causa raiz, acao corretiva e disposicao do material sao obrigatorias.");
    }
    setSaving(true);
    try {
      await api.post(`/cq/rncs/${selectedRnc.id}/encerrar`, {
        evidencia_resolucao: [
          `Causa raiz: ${closeForm.causa_raiz}`,
          `Acao corretiva: ${closeForm.acao_corretiva}`,
          `Disposicao: ${closeForm.disposicao_material}`,
          closeForm.evidencia_resolucao,
        ].filter(Boolean).join("\n"),
        com_concessao: closeForm.com_concessao,
        autorizacao_concessao: closeForm.autorizacao_concessao || undefined,
        observacoes: closeForm.evidencia_resolucao,
      });
      toast.success("RNC encerrada.");
      setCloseOpen(false);
      setSelectedRnc(null);
      setCloseForm(emptyClose);
      load();
    } catch (error) {
      toast.error(apiError(error, "Nao foi possivel encerrar RNC."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="dashboard-shell-wide space-y-5">
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="dashboard-eyebrow">Kuryos ERP · Controle de Qualidade</p>
          <h1 className="dashboard-title font-black">Qualidade</h1>
          <p className="text-sm text-muted-foreground">Fila de Inspecao e Nao Conformidades</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={load}><RefreshCw className="mr-2 h-4 w-4" />Atualizar</Button>
          <Button onClick={() => setRncOpen(true)}><Plus className="mr-2 h-4 w-4" />Nova RNC</Button>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        <Stat icon={FlaskConical} label="Em quarentena" value={ras.filter((ra) => ["rascunho", "em_analise"].includes(ra.status)).length} />
        <Stat icon={AlertTriangle} label="RNCs abertas" value={openRncs.length} tone="text-red-600" />
        <Stat icon={ClipboardList} label="Especificacoes" value={specs.length} />
        <Stat icon={ShieldCheck} label="Mais antiga aberta" value={`${Math.max(0, ...openRncs.map(daysOpen))}d`} tone="text-amber-600" />
      </div>

      <div className="dashboard-filterbar grid gap-2 md:grid-cols-[1fr_320px]">
        <div className="relative">
          <Search className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
          <Input className="pl-9" value={q} onChange={(event) => setQ(event.target.value)} placeholder="Buscar por lote, item, fornecedor, NF ou RNC..." />
        </div>
        <Select value={tab} onValueChange={setTab}>
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="fila">Fila de Inspecao</SelectItem>
            <SelectItem value="rncs">Nao Conformidades</SelectItem>
            <SelectItem value="especificacoes">Especificacoes</SelectItem>
            <SelectItem value="fornecedores">Desempenho de Fornecedor</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="dashboard-tabs grid grid-cols-2 md:grid-cols-4">
        {[
          ["fila", "Fila de Inspecao"],
          ["rncs", "Nao Conformidades"],
          ["especificacoes", "Especificacoes"],
          ["fornecedores", "Fornecedores"],
        ].map(([value, label]) => <button key={value} data-active={tab === value} className="dashboard-tab" onClick={() => setTab(value)}>{label}</button>)}
      </div>

      {loading ? <div className="flex h-56 items-center justify-center"><Loader2 className="h-8 w-8 animate-spin text-muted-foreground" /></div> : (
        <>
          {tab === "fila" && <div className="overflow-hidden rounded-xl border border-l-4 border-l-primary bg-card shadow-sm"><div className="border-b p-4"><b>Fila de inspecao ({filteredRas.length})</b></div><div className="overflow-x-auto"><table className="w-full min-w-[980px] text-sm"><thead className="bg-muted text-xs uppercase text-muted-foreground"><tr>{["RA", "Item / lote", "Entrada da Logistica", "Fornecedor", "Espera", "Status", "Acoes"].map((h) => <th key={h} className="p-3 text-left">{h}</th>)}</tr></thead><tbody>{filteredRas.map((ra) => <tr key={ra.id} className="border-b"><td className="p-3 font-mono font-bold">{ra.numero_ra}</td><td className="p-3"><b>{ra.item_nome || "-"}</b><p className="text-xs text-muted-foreground">Lote {ra.lote_numero || "-"} / {ra.quantidade_recebida || "-"} {ra.unidade || ""}</p></td><td className="p-3 text-xs">NF {ra.nf_numero || "-"}<br />{fmtDate(ra.nf_data)}<br />Amostra/certificado no laudo</td><td className="p-3">{ra.fornecedor_nome || "-"}</td><td className={`p-3 font-bold ${daysOpen(ra) > 3 ? "text-red-600" : ""}`}>{daysOpen(ra)}d</td><td className="p-3"><StatusBadge value={ra.status} /></td><td className="p-3"><div className="flex flex-wrap gap-2"><Button size="sm" onClick={() => navigate(`/cq/registros-analise/${ra.id}`)}>Laudar<ChevronRight className="ml-1 h-4 w-4" /></Button><Button size="sm" variant="outline" disabled={saving} onClick={() => decideRa(ra, "aprovado")}><Check className="mr-1 h-4 w-4" />Liberar</Button><Button size="sm" variant="outline" disabled={saving} onClick={() => decideRa(ra, "concessao")}>Concessao</Button><Button size="sm" variant="outline" disabled={saving} className="text-red-600" onClick={() => decideRa(ra, "reprovado")}>Reprovar</Button><Button size="sm" variant="outline" disabled={saving} onClick={() => decideRa(ra, "retido")}>Reter</Button></div></td></tr>)}{!filteredRas.length && <tr><td colSpan={7} className="p-10 text-center text-muted-foreground">Nenhum lote em fila.</td></tr>}</tbody></table></div></div>}

          {tab === "rncs" && <div className="overflow-hidden rounded-xl border border-l-4 border-l-primary bg-card shadow-sm"><div className="border-b p-4"><b>Nao conformidades ({openRncs.length})</b></div><div className="overflow-x-auto"><table className="w-full min-w-[980px] text-sm"><thead className="bg-muted text-xs uppercase text-muted-foreground"><tr>{["RNC", "Class.", "Origem / item", "Fornecedor", "Aberta ha", "Responsavel", "Status", "Acoes"].map((h) => <th key={h} className="p-3 text-left">{h}</th>)}</tr></thead><tbody>{openRncs.map((rnc) => <tr key={rnc.id} className="border-b"><td className="p-3 font-mono font-bold">{rnc.numero_rnc}</td><td className="p-3"><StatusBadge value={rnc.classificacao} /></td><td className="p-3"><b>{rnc.item_nome || "-"}</b><p className="text-xs text-muted-foreground">{rnc.origem || "-"} / lote {rnc.lote_numero || "-"}</p></td><td className="p-3">{rnc.fornecedor_nome || "-"}</td><td className="p-3 font-bold">{daysOpen(rnc)}d</td><td className="p-3">{rnc.responsavel_nome || "-"}</td><td className="p-3"><StatusBadge value={rnc.status} /></td><td className="p-3"><div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" onClick={() => navigate(`/cq/rncs/${rnc.id}`)}>Detalhe</Button><Button size="sm" disabled={saving || rnc.responsavel_id} onClick={() => assumeRnc(rnc)}>Assumir</Button><Button size="sm" variant="outline" disabled={saving} onClick={() => { setSelectedRnc(rnc); setCloseOpen(true); }}>Encerrar</Button></div></td></tr>)}{!openRncs.length && <tr><td colSpan={8} className="p-10 text-center text-muted-foreground">Nenhuma RNC aberta.</td></tr>}</tbody></table></div></div>}

          {tab === "especificacoes" && <div className="overflow-hidden rounded-xl border border-l-4 border-l-primary bg-card shadow-sm"><div className="border-b p-4"><b>Especificacoes de produto ({specs.length})</b><p className="text-sm text-muted-foreground">Consulta dos planos de inspecao. Edicao em Cadastros.</p></div><div className="overflow-x-auto"><table className="w-full min-w-[860px] text-sm"><thead className="bg-muted text-xs uppercase text-muted-foreground"><tr>{["SKU", "Produto", "Ensaio", "Faixa / criterio", "Numerico", "Critico", "Acao"].map((h) => <th key={h} className="p-3 text-left">{h}</th>)}</tr></thead><tbody>{specs.map((spec) => <tr key={spec.id} className="border-b"><td className="p-3 font-mono">{spec.produto.codigo_interno || "-"}</td><td className="p-3">{spec.produto.nome_produto}</td><td className="p-3 font-bold">{spec.name.replaceAll("_", " ")}</td><td className="p-3">{String(spec.value)}</td><td className="p-3">{spec.numeric ? <StatusBadge value="aprovado" /> : <StatusBadge value="pendente" />}</td><td className="p-3">{spec.critical ? <StatusBadge value="critica" /> : <StatusBadge value="menor" />}</td><td className="p-3"><Button size="sm" variant="outline" onClick={() => navigate("/cadastros")}>Abrir Cadastros</Button></td></tr>)}{!specs.length && <tr><td colSpan={7} className="p-10 text-center text-muted-foreground">Nenhuma especificacao cadastrada.</td></tr>}</tbody></table></div></div>}

          {tab === "fornecedores" && <div className="overflow-hidden rounded-xl border border-l-4 border-l-primary bg-card shadow-sm"><div className="border-b p-4"><b>Desempenho de fornecedor</b><p className="text-sm text-muted-foreground">Pior taxa primeiro. Concessao nao conta como aprovacao e RNC aberta deixa alerta.</p></div><div className="overflow-x-auto"><table className="w-full min-w-[780px] text-sm"><thead className="bg-muted text-xs uppercase text-muted-foreground"><tr>{["Fornecedor", "Taxa aprovacao", "RNCs", "RNC aberta", "Homologacao", "Acao"].map((h) => <th key={h} className="p-3 text-left">{h}</th>)}</tr></thead><tbody>{supplierRows.map((row) => <tr key={row.id} className="border-b"><td className="p-3 font-bold">{row.razao_social}</td><td className={`p-3 font-black ${row.taxa != null && row.taxa < 80 ? "text-red-600" : "text-emerald-600"}`}>{row.taxa == null ? "sem dado" : `${row.taxa}%`}</td><td className="p-3">{row.rncs}</td><td className="p-3">{row.abertas ? <StatusBadge value="aberta" /> : <StatusBadge value="aprovado" />}</td><td className="p-3"><StatusBadge value={row.status_homologacao} /></td><td className="p-3"><Button size="sm" variant="outline" onClick={() => navigate("/compras/fornecedores")}>Ver fornecedor</Button></td></tr>)}{!supplierRows.length && <tr><td colSpan={6} className="p-10 text-center text-muted-foreground">Nenhum fornecedor para analisar.</td></tr>}</tbody></table></div></div>}
        </>
      )}

      <Dialog open={rncOpen} onOpenChange={setRncOpen}>
        <DialogContent className="max-h-[88vh] max-w-3xl overflow-y-auto">
          <DialogHeader><DialogTitle>Nova RNC</DialogTitle></DialogHeader>
          <div className="grid gap-3 md:grid-cols-2">
            <Field label="Classificacao"><Select value={rncForm.classificacao} onValueChange={(value) => setRncForm({ ...rncForm, classificacao: value })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="critica">Critica</SelectItem><SelectItem value="maior">Maior</SelectItem><SelectItem value="menor">Menor</SelectItem></SelectContent></Select></Field>
            <Field label="Origem"><Select value={rncForm.origem} onValueChange={(value) => setRncForm({ ...rncForm, origem: value })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="recepcao_mp">Recepcao MP</SelectItem><SelectItem value="recepcao_embalagem">Recepcao embalagem</SelectItem><SelectItem value="processo_manipulacao">Producao</SelectItem><SelectItem value="produto_acabado">Produto acabado</SelectItem><SelectItem value="expedicao">Expedicao</SelectItem><SelectItem value="cliente">Reclamacao cliente</SelectItem></SelectContent></Select></Field>
            <Field label="Item"><Input value={rncForm.item_nome} onChange={(event) => setRncForm({ ...rncForm, item_nome: event.target.value })} /></Field>
            <Field label="Fornecedor"><Select value={rncForm.fornecedor_id || "none"} onValueChange={(value) => setRncForm({ ...rncForm, fornecedor_id: value === "none" ? "" : value })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="none">Sem fornecedor</SelectItem>{fornecedores.map((forn) => <SelectItem key={forn.id} value={forn.id}>{forn.razao_social}</SelectItem>)}</SelectContent></Select></Field>
            <Field label="Lote"><Input value={rncForm.lote_numero} onChange={(event) => setRncForm({ ...rncForm, lote_numero: event.target.value })} /></Field>
            <Field label="Quantidade afetada"><Input type="number" value={rncForm.quantidade_afetada} onChange={(event) => setRncForm({ ...rncForm, quantidade_afetada: event.target.value })} /></Field>
            <Field label="Unidade"><Input value={rncForm.unidade} onChange={(event) => setRncForm({ ...rncForm, unidade: event.target.value })} /></Field>
            <Field label="Disposicao imediata"><Select value={rncForm.disposicao_imediata} onValueChange={(value) => setRncForm({ ...rncForm, disposicao_imediata: value })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="devolucao">Devolver</SelectItem><SelectItem value="descarte">Descartar</SelectItem><SelectItem value="reprocesso">Retrabalhar</SelectItem><SelectItem value="concessao">Usar com concessao</SelectItem></SelectContent></Select></Field>
            <Field label="Prazo"><Input type="date" value={rncForm.prazo_resolucao} onChange={(event) => setRncForm({ ...rncForm, prazo_resolucao: event.target.value })} /></Field>
          </div>
          <Field label="Descricao"><Textarea value={rncForm.descricao} onChange={(event) => setRncForm({ ...rncForm, descricao: event.target.value })} /></Field>
          <DialogFooter><Button variant="outline" onClick={() => setRncOpen(false)}>Cancelar</Button><Button disabled={saving} onClick={createRnc}>Abrir RNC</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={closeOpen} onOpenChange={setCloseOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader><DialogTitle>Encerrar RNC {selectedRnc?.numero_rnc}</DialogTitle></DialogHeader>
          <div className="grid gap-3">
            <Field label="Causa raiz"><Textarea value={closeForm.causa_raiz} onChange={(event) => setCloseForm({ ...closeForm, causa_raiz: event.target.value })} /></Field>
            <Field label="Acao corretiva"><Textarea value={closeForm.acao_corretiva} onChange={(event) => setCloseForm({ ...closeForm, acao_corretiva: event.target.value })} /></Field>
            <Field label="Disposicao do material"><Select value={closeForm.disposicao_material} onValueChange={(value) => setCloseForm({ ...closeForm, disposicao_material: value, com_concessao: value === "concessao" })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="devolucao">Devolver</SelectItem><SelectItem value="descarte">Descartar</SelectItem><SelectItem value="reprocesso">Retrabalhar</SelectItem><SelectItem value="concessao">Usar com concessao</SelectItem><SelectItem value="aceitar">Aceitar</SelectItem></SelectContent></Select></Field>
            {closeForm.com_concessao && <Field label="Autorizacao da concessao"><Input value={closeForm.autorizacao_concessao} onChange={(event) => setCloseForm({ ...closeForm, autorizacao_concessao: event.target.value })} /></Field>}
            <Field label="Evidencia / observacoes"><Textarea value={closeForm.evidencia_resolucao} onChange={(event) => setCloseForm({ ...closeForm, evidencia_resolucao: event.target.value })} /></Field>
          </div>
          <DialogFooter><Button variant="outline" onClick={() => setCloseOpen(false)}>Cancelar</Button><Button disabled={saving} onClick={closeRnc}>Encerrar</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
